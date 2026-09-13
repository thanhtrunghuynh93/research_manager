"""Identity use cases: the only entry point other modules may import (docs/repo_layout.md §3.2).

Every mutation writes its audit row in the caller's transaction (architecture §5.3), and every
change to who may see what advances the workspace access epoch (AUTH-03).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope, load_project_ids
from app.core.clock import now
from app.core.config import get_settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthenticatedError,
    ValidationError,
)
from app.core.pagination import Page, clamp_limit
from app.core.types import ActorKind, Role
from app.identity import events, policies, repository, security  # noqa: F401  (policies register)
from app.identity.models import Invitation, PasswordReset, Session, User, UserState, Workspace
from app.identity.schemas import InvitationOut, UserOut, WorkspaceOut

log = logging.getLogger(__name__)

INVALID_CREDENTIALS = "invalid email or password"  # never says which of the two


@dataclass(frozen=True, slots=True)
class Invited:
    invitation: InvitationOut
    token: str


@dataclass(frozen=True, slots=True)
class LoggedIn:
    user: UserOut
    token: str


@dataclass(frozen=True, slots=True)
class AuthContext:
    scope: Scope
    user: UserOut
    session_id: UUID


@dataclass(frozen=True, slots=True)
class ResetRequested:
    user_id: UUID
    token: str


@dataclass(frozen=True, slots=True)
class RecoveryLink:
    user_id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Bootstrapped:
    workspace: WorkspaceOut
    user: UserOut
    token: str


async def scope_for(session: AsyncSession, user: User) -> Scope:
    """Compile the per-request Scope (architecture §6.1).

    A professor sees every project in the workspace, so no membership lookup is needed; the
    predicates in each module's policies.py branch on the role.
    """
    project_ids = (
        frozenset()
        if user.role is Role.PROF
        else await load_project_ids(session, user.workspace_id, user.id)
    )
    return Scope(
        workspace_id=user.workspace_id,
        user_id=user.id,
        role=user.role,
        project_ids=project_ids,
        access_epoch=await repository.access_epoch(session, user.workspace_id),
    )


# ------------------------------------------------------------------ reads


async def get_user(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    user = await repository.get_visible_user(session, scope, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return UserOut.model_validate(user)


async def list_users(
    session: AsyncSession, scope: Scope, *, limit: int | None = None, cursor: str | None = None
) -> Page[UserOut]:
    size = clamp_limit(limit)
    rows, next_cursor = await repository.list_visible_users(
        session, scope, limit=size, cursor=cursor
    )
    return Page(
        items=[UserOut.model_validate(row) for row in rows], next_cursor=next_cursor, limit=size
    )


async def advance_access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    """AUTH-03: call after any change elsewhere that narrows what someone may see.

    The projects module calls it when a membership ends; cached answers and snapshots built under
    the previous epoch stop being served (architecture §6.3).
    """
    return await repository.bump_access_epoch(session, workspace_id)


async def access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    """Job-level read: the epoch a snapshot or cached answer was built under (AUTH-03)."""
    return await repository.access_epoch(session, workspace_id)


async def ai_budgets(session: AsyncSession, workspace_id: UUID) -> dict[str, Any]:
    """The workspace's monthly model-spending limits (requirements §11 "Cost control").

    A job-level read: the gateway checks a budget with no Scope to hand, and an empty result means
    no limit has been configured rather than a limit of zero.
    """
    return await repository.ai_budgets(session, workspace_id)


async def set_ai_budgets(
    session: AsyncSession, scope: Scope, budgets: dict[str, Any]
) -> dict[str, Any]:
    """The professor's decision about what may be spent, audited like any other setting."""
    scope.require_prof()
    before = await repository.ai_budgets(session, scope.workspace_id)
    after = await repository.set_ai_budgets(session, scope.workspace_id, budgets)
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="workspace.ai_budgets_set",
        target_table="workspaces",
        target_id=scope.workspace_id,
        before=before,
        after=after,
    )
    await session.flush()
    return after


async def workspace_ids(session: AsyncSession) -> list[UUID]:
    """Job-level read: the periodic tasks act on every workspace and have no Scope."""
    return await repository.workspace_ids(session)


async def system_scope(session: AsyncSession, workspace_id: UUID) -> Scope:
    """The Scope a scheduled task acts under: the workspace's professor, or nobody.

    Built rather than faked: the same predicates then apply to a job as to a request, and a task
    cannot reach further than the professor could.
    """
    professors = await repository.professor_ids(session, workspace_id)
    return Scope(
        workspace_id=workspace_id,
        user_id=professors[0] if professors else workspace_id,
        role=Role.PROF,
        project_ids=frozenset(),
        access_epoch=await repository.access_epoch(session, workspace_id),
    )


async def professor_ids(session: AsyncSession, workspace_id: UUID) -> list[UUID]:
    """Job-level read: who to address a professor-facing notification to (UI-07)."""
    return await repository.professor_ids(session, workspace_id)


async def contact_for_job(session: AsyncSession, user_id: UUID) -> UserOut | None:
    """Job-level read: the address and language to send to. The worker has no Scope."""
    user = await repository.get_user_by_id(session, user_id)
    return None if user is None else UserOut.model_validate(user)


# ------------------------------------------------------------------ enrollment (AUTH-01)


async def invite_user(
    session: AsyncSession,
    scope: Scope,
    *,
    email: str,
    display_name: str | None = None,
    role: Role = Role.STUDENT,
) -> Invited:
    """AUTH-01: only the professor enrolls people, and only by invitation."""
    scope.require_prof()
    address = security.normalize_email(email)
    at = now()

    user = await repository.get_user_by_email(session, address)
    if user is not None and user.state is not UserState.INVITED:
        raise ConflictError("a user with this email already exists")
    if user is not None and user.workspace_id != scope.workspace_id:
        raise ConflictError("a user with this email already exists")

    if user is None:
        user = User(
            workspace_id=scope.workspace_id,
            role=role,
            email=address,
            display_name=display_name or address.split("@")[0],
            state=UserState.INVITED,
        )
        session.add(user)
        await session.flush()
    else:
        # Re-invitation: the previous link stops working the moment a new one is issued.
        user.role = role
        if display_name:
            user.display_name = display_name
        await repository.revoke_pending_invitations(session, user.id, at)

    token, token_hash = security.mint_token()
    invitation = Invitation(
        workspace_id=scope.workspace_id,
        user_id=user.id,
        email=address,
        role=role,
        token_hash=token_hash,
        expires_at=at + security.INVITATION_TTL,
        created_by=scope.user_id,
    )
    session.add(invitation)
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.invited",
        target_table="users",
        target_id=user.id,
        after={"email": address, "role": role.value},
    )
    await session.flush()

    await events.emit(
        events.InvitationCreated(
            workspace_id=scope.workspace_id,
            user_id=user.id,
            email=address,
            display_name=user.display_name,
            locale=user.locale,
            token=token,
            expires_at=invitation.expires_at,
        ),
        session,
    )
    _log_token_link("invitation", address, f"/accept-invitation?token={token}")
    return Invited(invitation=InvitationOut.model_validate(invitation), token=token)


async def accept_invitation(
    session: AsyncSession, *, token: str, password: str, display_name: str | None = None
) -> UserOut:
    at = now()
    invitation = await repository.get_invitation_by_token(session, security.hash_token(token))
    if invitation is None or not _invitation_is_open(invitation, at):
        raise ValidationError("invitation token is invalid, used, or expired")

    user = await repository.get_user_in_workspace(
        session, invitation.workspace_id, invitation.user_id
    )
    if user is None:
        raise ValidationError("invitation token is invalid, used, or expired")
    if user.state is UserState.DEACTIVATED:
        # AUTH-03: deactivation has to be durable. An invitation issued before it — or still open
        # when it happened — must not be a way for the account holder to reinstate and sign in.
        # `deactivate_user` revokes open invitations, so reaching here means one was issued after.
        raise ValidationError("invitation token is invalid, used, or expired")

    # Hash before stamping the invitation: a rejected password must leave the link usable.
    password_hash = security.hash_password(password)
    user.password_hash = password_hash
    user.state = UserState.ACTIVE
    if user.role is not invitation.role:
        # AUTH-01: the professor's most recent decision wins. `set_role` applies to an invited
        # user too, and there is no route to reissue the invitation, so taking the role off the
        # invitation here would silently revert a change they already made and audited.
        log.info(
            "invitation for %s carried role %s; keeping the role %s set since",
            user.id,
            invitation.role.value,
            user.role.value,
        )
    if display_name:
        user.display_name = display_name
    invitation.accepted_at = at

    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="invitation.accepted",
        target_table="users",
        target_id=user.id,
        after={"state": user.state.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


def _invitation_is_open(invitation: Invitation, at: datetime) -> bool:
    return (
        invitation.accepted_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > at
    )


# ------------------------------------------------------------------ sessions (AUTH-01, AUTH-03)


async def login(session: AsyncSession, *, email: str, password: str) -> LoggedIn:
    try:
        address = security.normalize_email(email)
    except ValidationError:
        security.verify_password(password, None)  # equalise timing for a malformed address
        raise UnauthenticatedError(INVALID_CREDENTIALS) from None

    user = await repository.get_user_by_email(session, address)
    stored = user.password_hash if user is not None and user.state is UserState.ACTIVE else None
    if not security.verify_password(password, stored) or user is None:
        raise UnauthenticatedError(INVALID_CREDENTIALS)

    if security.needs_rehash(user.password_hash or ""):
        user.password_hash = security.hash_password(password)

    return await _open_session(session, user)


async def start_session(session: AsyncSession, *, user_id: UUID) -> LoggedIn:
    """Open a session for someone who has just proved control of their mailbox.

    Used by invitation acceptance, where the token itself is the proof.
    """
    user = await repository.get_user_by_id(session, user_id)
    if user is None or user.state is not UserState.ACTIVE:
        raise UnauthenticatedError(INVALID_CREDENTIALS)
    return await _open_session(session, user)


async def _open_session(session: AsyncSession, user: User) -> LoggedIn:
    at = now()
    token, token_hash = security.mint_token()
    row = Session(
        workspace_id=user.workspace_id,
        user_id=user.id,
        token_hash=token_hash,
        created_at=at,
        last_seen_at=at,
        expires_at=security.absolute_expiry(at),
    )
    session.add(row)
    await session.flush()
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="session.created",
        target_table="sessions",
        target_id=row.id,
    )
    await session.flush()
    return LoggedIn(user=UserOut.model_validate(user), token=token)


async def resolve_session(session: AsyncSession, *, token: str) -> AuthContext | None:
    """Return the caller's Scope, or None when the token is unknown, revoked, or expired."""
    row = await repository.get_session_by_token(session, security.hash_token(token))
    if row is None:
        return None

    at = now()
    if row.expires_at <= at or security.is_idle_expired(row.last_seen_at, now=at):
        return None

    user = await repository.get_user_in_workspace(session, row.workspace_id, row.user_id)
    if user is None or user.state is not UserState.ACTIVE:
        return None

    if security.should_touch(row.last_seen_at, now=at):
        row.last_seen_at = at
        await session.flush()

    return AuthContext(
        scope=await scope_for(session, user),
        user=UserOut.model_validate(user),
        session_id=row.id,
    )


async def logout(session: AsyncSession, *, token: str) -> None:
    revoked = await repository.revoke_session_by_token(session, security.hash_token(token), now())
    _audit_session_revoked(session, revoked)
    await session.flush()


async def logout_session(session: AsyncSession, *, session_id: UUID) -> None:
    """Sign out the caller's own session.

    Identified by the resolved context rather than by the cookie value.
    """
    revoked = await repository.revoke_session_by_id(session, session_id, now())
    _audit_session_revoked(session, revoked)
    await session.flush()


def _audit_session_revoked(session: AsyncSession, revoked: Session | None) -> None:
    if revoked is None:
        return
    write_audit(
        session,
        workspace_id=revoked.workspace_id,
        actor_id=revoked.user_id,
        action="session.revoked",
        target_table="sessions",
        target_id=revoked.id,
    )


# ------------------------------------------------------------------ account lifecycle


async def deactivate_user(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    """AUTH-03: deactivation ends every session and advances the epoch in one transaction."""
    scope.require_prof()
    if user_id == scope.user_id:
        raise ForbiddenError("a professor cannot deactivate their own account")

    user = await _require_user(session, scope, user_id)
    if user.state is UserState.DEACTIVATED:
        return UserOut.model_validate(user)

    at = now()
    before = user.state.value
    user.state = UserState.DEACTIVATED
    user.deactivated_at = at
    await repository.revoke_sessions_for_user(session, user.id, at)
    # An open invitation is a credential too: accepting one sets a password and starts a session.
    await repository.revoke_pending_invitations(session, user.id, at)
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.deactivated",
        target_table="users",
        target_id=user.id,
        before={"state": before},
        after={"state": user.state.value},
    )
    await session.flush()
    await events.emit(
        events.UserDeactivated(
            workspace_id=scope.workspace_id, user_id=user.id, actor_id=scope.user_id
        ),
        session,
    )
    return UserOut.model_validate(user)


async def reactivate_user(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    scope.require_prof()
    user = await _require_user(session, scope, user_id)
    if user.state is not UserState.DEACTIVATED:
        return UserOut.model_validate(user)

    before = user.state.value
    # Someone who never accepted their invitation returns to `invited`, not to a login they lack.
    user.state = UserState.ACTIVE if user.password_hash else UserState.INVITED
    user.deactivated_at = None
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.reactivated",
        target_table="users",
        target_id=user.id,
        before={"state": before},
        after={"state": user.state.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def set_role(session: AsyncSession, scope: Scope, user_id: UUID, role: Role) -> UserOut:
    """AUTH-01: only the professor changes roles, and never their own."""
    scope.require_prof()
    if user_id == scope.user_id:
        raise ForbiddenError("a professor cannot change their own role")

    user = await _require_user(session, scope, user_id)
    if user.role is role:
        return UserOut.model_validate(user)

    before = user.role.value
    user.role = role
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.role_changed",
        target_table="users",
        target_id=user.id,
        before={"role": before},
        after={"role": role.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def update_profile(
    session: AsyncSession,
    scope: Scope,
    *,
    display_name: str | None = None,
    locale: str | None = None,
) -> UserOut:
    user = await _require_user(session, scope, scope.user_id)
    before = {"display_name": user.display_name, "locale": user.locale}
    if display_name:
        user.display_name = display_name
    if locale:
        user.locale = locale
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.profile_updated",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"display_name": user.display_name, "locale": user.locale},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def _require_user(session: AsyncSession, scope: Scope, user_id: UUID) -> User:
    user = await repository.get_user_in_workspace(session, scope.workspace_id, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return user


# ------------------------------------------------------------------ recovery (AUTH-01)


async def request_password_reset(session: AsyncSession, *, email: str) -> ResetRequested | None:
    """Return None for an address that cannot receive a reset, without saying why."""
    try:
        address = security.normalize_email(email)
    except ValidationError:
        return None

    user = await repository.get_user_by_email(session, address)
    if user is None or user.state is not UserState.ACTIVE:
        return None

    at = now()
    await repository.revoke_pending_password_resets(session, user.id, at)
    token, token_hash = security.mint_token()
    reset = PasswordReset(
        workspace_id=user.workspace_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=at + security.PASSWORD_RESET_TTL,
    )
    session.add(reset)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="password_reset.requested",
        target_table="users",
        target_id=user.id,
    )
    await session.flush()

    await events.emit(
        events.PasswordResetRequested(
            workspace_id=user.workspace_id,
            user_id=user.id,
            email=address,
            display_name=user.display_name,
            locale=user.locale,
            token=token,
            expires_at=reset.expires_at,
        ),
        session,
    )
    _log_token_link("password reset", address, f"/reset-password?token={token}")
    return ResetRequested(user_id=user.id, token=token)


async def reset_password(session: AsyncSession, *, token: str, password: str) -> UserOut:
    at = now()
    reset = await repository.get_password_reset_by_token(session, security.hash_token(token))
    if (
        reset is None
        or reset.used_at is not None
        or reset.revoked_at is not None
        or reset.expires_at <= at
    ):
        raise ValidationError("reset token is invalid, used, or expired")

    user = await repository.get_user_in_workspace(session, reset.workspace_id, reset.user_id)
    if user is None or user.state is not UserState.ACTIVE:
        raise ValidationError("reset token is invalid, used, or expired")

    # Hash before consuming the token: a rejected password must leave the link usable.
    user.password_hash = security.hash_password(password)
    reset.used_at = at
    await repository.revoke_sessions_for_user(session, user.id, at)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=user.id,
        action="password_reset.completed",
        target_table="users",
        target_id=user.id,
    )
    await session.flush()
    return UserOut.model_validate(user)


# ------------------------------------------------------------------ bootstrap and break-glass


async def bootstrap_workspace(
    session: AsyncSession,
    *,
    name: str,
    prof_email: str,
    prof_display_name: str,
    timezone: str = "Asia/Ho_Chi_Minh",
) -> Bootstrapped:
    """Create the workspace and its professor. Run once, from the host (app.cli)."""
    address = security.normalize_email(prof_email)
    if await repository.get_user_by_email(session, address) is not None:
        raise ConflictError("a user with this email already exists")

    at = now()
    workspace = Workspace(name=name, timezone=timezone)
    session.add(workspace)
    await session.flush()

    user = User(
        workspace_id=workspace.id,
        role=Role.PROF,
        email=address,
        display_name=prof_display_name,
        state=UserState.INVITED,
    )
    session.add(user)
    await session.flush()
    workspace.owner_id = user.id

    token, token_hash = security.mint_token()
    session.add(
        Invitation(
            workspace_id=workspace.id,
            user_id=user.id,
            email=address,
            role=Role.PROF,
            token_hash=token_hash,
            expires_at=at + security.INVITATION_TTL,
        )
    )
    write_audit(
        session,
        workspace_id=workspace.id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="workspace.bootstrapped",
        target_table="workspaces",
        target_id=workspace.id,
        after={"owner_email": address},
    )
    await session.flush()
    return Bootstrapped(
        workspace=WorkspaceOut.model_validate(workspace),
        user=UserOut.model_validate(user),
        token=token,
    )


async def recover_professor(session: AsyncSession, *, email: str) -> RecoveryLink:
    """AUTH-01 break-glass: restore professor access from the host shell only.

    Runs from `app.cli breakglass recover-professor`, never from the API. It issues a short-lived
    single-use recovery link rather than a password, so the secret is handed over out of band, and
    it writes a system-actor audit row (docs/runbooks/break-glass.md, architecture §6.2).
    """
    address = security.normalize_email(email)
    user = await repository.get_user_by_email(session, address)
    if user is None:
        raise NotFoundError(f"no account with the address {address}")

    before = {"role": user.role.value, "state": user.state.value}
    # The lock-out may be the demotion or deactivation itself, so recovery undoes both.
    user.role = Role.PROF
    user.state = UserState.ACTIVE
    user.deactivated_at = None
    await repository.bump_access_epoch(session, user.workspace_id)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="identity.break_glass",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"role": Role.PROF.value, "state": UserState.ACTIVE.value},
    )
    return await _issue_recovery_link(session, user, ttl=security.BREAK_GLASS_RESET_TTL)


async def transfer_professor(
    session: AsyncSession, *, from_email: str, to_email: str, display_name: str | None = None
) -> RecoveryLink:
    """AUTH-01 break-glass: hand the workspace to another person in one transaction."""
    previous_address = security.normalize_email(from_email)
    successor_address = security.normalize_email(to_email)
    if previous_address == successor_address:
        raise ValidationError("the successor must be a different account")

    previous = await repository.get_user_by_email(session, previous_address)
    if previous is None:
        raise NotFoundError(f"no account with the address {previous_address}")

    workspace_id = previous.workspace_id
    successor = await repository.get_user_by_email(session, successor_address)
    if successor is not None and successor.workspace_id != workspace_id:
        raise ConflictError("that email belongs to another workspace")
    if successor is None:
        successor = User(
            workspace_id=workspace_id,
            role=Role.PROF,
            email=successor_address,
            display_name=display_name or successor_address.split("@")[0],
            state=UserState.ACTIVE,
        )
        session.add(successor)
        await session.flush()

    at = now()
    successor_before = {"role": successor.role.value, "state": successor.state.value}
    previous_before = {"state": previous.state.value}
    successor.role = Role.PROF
    successor.state = UserState.ACTIVE
    successor.deactivated_at = None
    if display_name:
        successor.display_name = display_name

    previous.state = UserState.DEACTIVATED
    previous.deactivated_at = at
    await repository.revoke_sessions_for_user(session, previous.id, at)
    await repository.bump_access_epoch(session, workspace_id)

    for target, before, after in (
        (
            successor,
            successor_before,
            {"role": Role.PROF.value, "state": UserState.ACTIVE.value},
        ),
        (previous, previous_before, {"state": UserState.DEACTIVATED.value}),
    ):
        write_audit(
            session,
            workspace_id=workspace_id,
            actor_id=None,
            actor_kind=ActorKind.SYSTEM,
            action="identity.break_glass_transfer",
            target_table="users",
            target_id=target.id,
            before=before,
            after=after,
        )
    return await _issue_recovery_link(session, successor, ttl=security.BREAK_GLASS_RESET_TTL)


async def _issue_recovery_link(
    session: AsyncSession, user: User, *, ttl: timedelta
) -> RecoveryLink:
    at = now()
    await repository.revoke_pending_password_resets(session, user.id, at)
    token, token_hash = security.mint_token()
    reset = PasswordReset(
        workspace_id=user.workspace_id,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=at + ttl,
    )
    session.add(reset)
    await session.flush()

    # The notifications module tells the address on record that recovery happened (step 4).
    await events.emit(
        events.PasswordResetRequested(
            workspace_id=user.workspace_id,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            locale=user.locale,
            token=token,
            expires_at=reset.expires_at,
        ),
        session,
    )
    return RecoveryLink(user_id=user.id, token=token, expires_at=reset.expires_at)


def _log_token_link(kind: str, address: str, path: str) -> None:
    """Development affordance until the notifications module sends these emails (REP-08, step 4).

    Outside dev only the fact of the delivery is logged; the token never reaches the log.
    """
    settings = get_settings()
    if settings.env == "dev":
        log.info("%s link for %s: %s%s", kind, address, settings.public_url, path)
    else:
        log.info("%s issued for %s", kind, address)
