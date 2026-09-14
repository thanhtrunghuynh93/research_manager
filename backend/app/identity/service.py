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

    A workspace may hold several professors (ADR 0011). `professor_ids` is ordered, so the borrowed
    identity is stable across runs, and `is_system` marks it as a lens rather than an author — a
    write made under this Scope is audited as the system, not as whoever sorted first.
    """
    professors = await repository.professor_ids(session, workspace_id)
    return Scope(
        workspace_id=workspace_id,
        user_id=professors[0] if professors else workspace_id,
        role=Role.PROF,
        project_ids=frozenset(),
        access_epoch=await repository.access_epoch(session, workspace_id),
        is_system=True,
    )


async def professor_ids(session: AsyncSession, workspace_id: UUID) -> list[UUID]:
    """Job-level read: who to address a professor-facing notification to (UI-07)."""
    return await repository.professor_ids(session, workspace_id)


async def workspace_for_job(session: AsyncSession, workspace_id: UUID) -> WorkspaceOut | None:
    """Job-level read: the workspace an email names itself after. The worker has no Scope."""
    workspace = await session.get(Workspace, workspace_id)
    return None if workspace is None else WorkspaceOut.model_validate(workspace)


async def contact_for_job(session: AsyncSession, user_id: UUID) -> UserOut | None:
    """Job-level read: the address to send to. The worker has no Scope."""
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
    """AUTH-01: only a professor enrolls people, and only by invitation.

    Any professor may invite a colleague as a professor; that is the only way a professor is added
    short of bootstrap or break-glass (ADR 0011). A role is fixed at acceptance: until then an
    invitation is an offer, and reissuing it at a different role is allowed — the role travels on
    the user row, which the re-invitation branch below updates. An account that has already
    accepted is refused here, so acceptance is the point after which only break-glass can move it.
    """
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
        # AUTH-01: the most recent invitation wins. Re-inviting a not-yet-accepted account at a
        # different role updates the user row and leaves this older invitation's copy behind, so
        # taking the role off the invitation here would revert a decision already made and audited.
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
    """AUTH-03: deactivation ends every session and advances the epoch in one transaction.

    Suspension, not removal: `reactivate_user` undoes it and project memberships are untouched.
    To take a student off the roll, use `remove_student`.
    """
    scope.require_prof()
    if user_id == scope.user_id:
        raise ForbiddenError("a professor cannot deactivate their own account")

    user = await _require_user(session, scope, user_id)
    if user.role is Role.PROF:
        # ADR 0011: professors are equal over students and unequal over each other. Ejecting a
        # colleague is deliberate enough to require the host shell, where it is audited as system.
        raise ForbiddenError(
            "a professor account is deactivated through the break-glass procedure, not the API"
        )
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


async def remove_student(session: AsyncSession, scope: Scope, user_id: UUID) -> UserOut:
    """AUTH-01/PROJ-02: take a student off the roll — memberships end, then the account closes.

    Deactivating alone is not removal. Obligations are derived from memberships and nothing in that
    path filters on user state, so a student who only lost their login keeps accruing weekly
    obligations and the reminders that go with them. Ending the memberships in the same transaction
    is what stops that (ADR 0011).

    The ledger survives: submitted reports, assessments, artifacts and attributed commits stay, and
    the membership rows remain as history carrying `left_on`. Removal is not reversible — a student
    who returns is invited again and comes back with fresh memberships.

    `UserRemoved` carries the membership-ending to the projects module, which subscribes to it.
    identity sits below projects in the layer order and so cannot call it directly.
    """
    scope.require_prof()
    if user_id == scope.user_id:
        raise ForbiddenError("a professor cannot remove their own account")

    user = await _require_user(session, scope, user_id)
    if user.role is Role.PROF:
        # ADR 0011: the API removes students. A professor leaving is a break-glass transfer.
        raise ForbiddenError(
            "a professor account is removed through the break-glass procedure, not the API"
        )

    at = now()
    before = user.state.value
    already_closed = user.state is UserState.DEACTIVATED
    user.state = UserState.DEACTIVATED
    user.deactivated_at = user.deactivated_at if already_closed else at
    await repository.revoke_sessions_for_user(session, user.id, at)
    # An open invitation is a credential too: accepting one sets a password and starts a session.
    await repository.revoke_pending_invitations(session, user.id, at)
    await repository.bump_access_epoch(session, scope.workspace_id)
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.removed",
        target_table="users",
        target_id=user.id,
        before={"state": before},
        after={"state": user.state.value},
    )
    await session.flush()
    await events.emit(
        events.UserRemoved(
            workspace_id=scope.workspace_id, user_id=user.id, actor_id=scope.user_id, at=at
        ),
        session,
    )
    return UserOut.model_validate(user)


async def update_profile(
    session: AsyncSession,
    scope: Scope,
    *,
    display_name: str | None = None,
) -> UserOut:
    user = await _require_user(session, scope, scope.user_id)
    before = {"display_name": user.display_name}
    if display_name:
        user.display_name = display_name
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="user.profile_updated",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"display_name": user.display_name},
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
    # The break-glass contact, not a privilege: professors are co-equal and nothing authorizes
    # against this column (ADR 0011). `transfer_professor` moves it.
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


async def _require_another_active_professor(
    session: AsyncSession, workspace_id: UUID, *, excluding: UUID
) -> None:
    """ADR 0011: a workspace never runs out of professors.

    With one professor this was guaranteed by the self-action guards — nobody could act on the only
    account that mattered. With a set of co-equal professors that reasoning no longer holds, so the
    invariant is checked rather than inferred.
    """
    if await repository.count_active_professors(session, workspace_id, excluding=excluding) == 0:
        raise ConflictError(
            "this is the only active professor in the workspace; transfer the account instead"
        )


async def demote_professor(session: AsyncSession, *, email: str) -> UserOut:
    """AUTH-01 break-glass: return a professor to the student role, from the host shell only.

    Not reachable from the API: professors are equal over students and unequal over each other, so
    one cannot unilaterally demote another (ADR 0011).
    """
    address = security.normalize_email(email)
    user = await repository.get_user_by_email(session, address)
    if user is None:
        raise NotFoundError(f"no account with the address {address}")
    if user.role is not Role.PROF:
        raise ValidationError(f"{address} is not a professor")
    await _require_another_active_professor(session, user.workspace_id, excluding=user.id)

    before = {"role": user.role.value}
    user.role = Role.STUDENT
    await repository.bump_access_epoch(session, user.workspace_id)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="identity.break_glass_demote",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"role": Role.STUDENT.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


async def deactivate_professor(session: AsyncSession, *, email: str) -> UserOut:
    """AUTH-01 break-glass: close a professor account, from the host shell only (ADR 0011)."""
    address = security.normalize_email(email)
    user = await repository.get_user_by_email(session, address)
    if user is None:
        raise NotFoundError(f"no account with the address {address}")
    if user.role is not Role.PROF:
        raise ValidationError(f"{address} is not a professor")
    if user.state is UserState.DEACTIVATED:
        return UserOut.model_validate(user)
    await _require_another_active_professor(session, user.workspace_id, excluding=user.id)

    at = now()
    before = {"state": user.state.value}
    user.state = UserState.DEACTIVATED
    user.deactivated_at = at
    await repository.revoke_sessions_for_user(session, user.id, at)
    await repository.revoke_pending_invitations(session, user.id, at)
    await repository.bump_access_epoch(session, user.workspace_id)
    write_audit(
        session,
        workspace_id=user.workspace_id,
        actor_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="identity.break_glass_deactivate",
        target_table="users",
        target_id=user.id,
        before=before,
        after={"state": user.state.value},
    )
    await session.flush()
    return UserOut.model_validate(user)


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
    # The owner is the workspace's break-glass contact (ADR 0011). A transfer moves it; leaving it
    # on a deactivated account would point the next recovery at someone who has already left.
    workspace = await session.get(Workspace, workspace_id)
    if workspace is not None and workspace.owner_id == previous.id:
        workspace.owner_id = successor.id
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
            token=token,
            expires_at=reset.expires_at,
        ),
        session,
    )
    return RecoveryLink(user_id=user.id, token=token, expires_at=reset.expires_at)


def _log_token_link(kind: str, address: str, path: str) -> None:
    """Development convenience beside the email, which notifications now sends (AUTH-01).

    Kept because a dev stack without SMTP still needs a way in, and because a link in the log is
    faster to reach than one in Mailpit. Outside dev only the fact of the delivery is logged; the
    token never reaches the log.
    """
    settings = get_settings()
    if settings.env == "dev":
        log.info("%s link for %s: %s%s", kind, address, settings.public_url, path)
    else:
        log.info("%s issued for %s", kind, address)
