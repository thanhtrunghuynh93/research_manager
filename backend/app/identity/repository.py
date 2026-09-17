"""Queries over identity tables. No business rules here (docs/repo_layout.md §3.2).

Reads on behalf of a caller take a Scope and apply `visible_to`. The lookups used before a session
exists — login, invitation acceptance, password recovery — are marked as such: they authenticate the
caller rather than serve one, and every one of them is reached only through identity.service.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.pagination import cursor_after, encode_cursor
from app.core.types import Role
from app.identity.models import (
    Invitation,
    PasswordReset,
    Session,
    User,
    UserState,
    Workspace,
    WorkspaceMember,
)


async def get_workspace(session: AsyncSession, workspace_id: UUID) -> Workspace | None:
    return await session.get(Workspace, workspace_id)


async def workspaces_owned_by(
    session: AsyncSession, owner_id: UUID, *, include_archived: bool = False
) -> list[Workspace]:
    """Every workspace this professor administers, oldest first.

    Archived ones are excluded by default. An archived workspace is finished — empty of accounts
    by the time it is archived, and nothing can be invited into it — so listing it offers a row
    with no action on it.
    """
    statement = select(Workspace).where(Workspace.owner_id == owner_id)
    if not include_archived:
        statement = statement.where(Workspace.archived_at.is_(None))
    return list(
        (await session.execute(statement.order_by(Workspace.created_at, Workspace.id)))
        .scalars()
        .all()
    )


async def count_active_users(session: AsyncSession, workspace_id: UUID) -> int:
    """Accounts that still belong to this workspace and can sign in.

    Counted through `workspace_members`, not `users.workspace_id`: a professor who belongs here but
    is working elsewhere is still in the workspace, and counting the column would let it be
    archived out from under them (ADR 0015).
    """
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(WorkspaceMember)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    User.state == UserState.ACTIVE,
                )
            )
        ).scalar_one()
    )


async def workspaces_joined_by(
    session: AsyncSession, user_id: UUID, *, include_archived: bool = False
) -> list[Workspace]:
    """Every workspace this account belongs to, oldest first. Archived ones are excluded."""
    statement = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
    )
    if not include_archived:
        statement = statement.where(Workspace.archived_at.is_(None))
    return list(
        (await session.execute(statement.order_by(Workspace.created_at, Workspace.id)))
        .scalars()
        .all()
    )


async def membership(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> WorkspaceMember | None:
    return (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def add_membership(session: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
    """Idempotent: joining a workspace you already belong to changes nothing."""
    if await membership(session, workspace_id, user_id) is None:
        session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id))
        await session.flush()


async def remove_membership(session: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
    row = await membership(session, workspace_id, user_id)
    if row is not None:
        await session.delete(row)
        await session.flush()


async def count_active_professors_in(
    session: AsyncSession, workspace_id: UUID, *, excluding: UUID
) -> int:
    """Professors who would still belong here if `excluding` left."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(WorkspaceMember)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id != excluding,
                    User.role == Role.PROF,
                    User.state == UserState.ACTIVE,
                )
            )
        ).scalar_one()
    )


async def access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    epoch = (
        await session.execute(select(Workspace.access_epoch).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    return epoch if epoch is not None else 0


async def access_epochs(session: AsyncSession, workspace_ids: Iterable[UUID]) -> dict[UUID, int]:
    """Every epoch a read may span, in one round trip rather than one query per workspace."""
    ids = list(workspace_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(Workspace.id, Workspace.access_epoch).where(Workspace.id.in_(ids))
    )
    return {workspace_id: epoch for workspace_id, epoch in rows.all()}


async def bump_access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    """AUTH-03: invalidate caches and snapshots built under the previous epoch."""
    return (
        await session.execute(
            update(Workspace)
            .where(Workspace.id == workspace_id)
            .values(access_epoch=Workspace.access_epoch + 1)
            .returning(Workspace.access_epoch)
        )
    ).scalar_one()


async def ai_budgets(session: AsyncSession, workspace_id: UUID) -> dict[str, Any]:
    budgets = (
        await session.execute(select(Workspace.ai_budgets).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    return dict(budgets) if budgets else {}


async def set_ai_budgets(
    session: AsyncSession, workspace_id: UUID, budgets: dict[str, Any]
) -> dict[str, Any]:
    return dict(
        (
            await session.execute(
                update(Workspace)
                .where(Workspace.id == workspace_id)
                .values(ai_budgets=budgets)
                .returning(Workspace.ai_budgets)
            )
        ).scalar_one()
    )


async def get_visible_user(session: AsyncSession, scope: Scope, user_id: UUID) -> User | None:
    return (
        await session.execute(select(User).where(User.id == user_id, visible_to(scope, User)))
    ).scalar_one_or_none()


async def list_visible_users(
    session: AsyncSession, scope: Scope, *, limit: int, cursor: str | None
) -> tuple[list[User], str | None]:
    """Keyset pagination on the primary key, which is UUIDv7 and therefore in creation order.

    One predicate, whatever it spans. `visible_to` compiles the User policy, which is keyed by
    membership and by `Scope.workspace_ids` — so a professor in several workspaces gets one row per
    person rather than one per membership, and a student gets themselves.
    """
    statement = select(User).where(visible_to(scope, User)).order_by(User.id).limit(limit + 1)
    after = cursor_after(cursor)
    if after is not None:
        statement = statement.where(User.id > after)

    rows = list((await session.execute(statement)).scalars().all())
    if len(rows) <= limit:
        return rows, None
    return rows[:limit], encode_cursor({"after": str(rows[limit - 1].id)})


async def get_user_in_workspace(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> User | None:
    """Service-internal lookup for a write; the caller has already checked the role."""
    return (
        await session.execute(
            select(User).where(User.id == user_id, User.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    """Unauthenticated lookup: used when a token, not a session, identifies the user."""
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Unauthenticated lookup: login and recovery run before a Scope exists."""
    return (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def professor_ids(session: AsyncSession, workspace_id: UUID) -> list[UUID]:
    """Ordered oldest first. A workspace may hold several professors (ADR 0011), and callers that
    take only the first — `system_scope` does — must get the same one on every run."""
    rows = await session.execute(
        select(User.id)
        .where(
            User.workspace_id == workspace_id,
            User.role == Role.PROF,
            User.state == UserState.ACTIVE,
        )
        .order_by(User.created_at, User.id)
    )
    return list(rows.scalars().all())


async def count_active_professors(
    session: AsyncSession, workspace_id: UUID, *, excluding: UUID | None = None
) -> int:
    """How many professors would remain if `excluding` stopped being one (ADR 0011)."""
    statement = (
        select(func.count())
        .select_from(User)
        .where(
            User.workspace_id == workspace_id,
            User.role == Role.PROF,
            User.state == UserState.ACTIVE,
        )
    )
    if excluding is not None:
        statement = statement.where(User.id != excluding)
    return int((await session.execute(statement)).scalar_one())


async def get_invitation_by_token(session: AsyncSession, token_hash: str) -> Invitation | None:
    """Unauthenticated lookup: the token is the credential."""
    return (
        await session.execute(select(Invitation).where(Invitation.token_hash == token_hash))
    ).scalar_one_or_none()


async def revoke_pending_invitations(session: AsyncSession, user_id: UUID, at: datetime) -> None:
    await session.execute(
        update(Invitation)
        .where(
            Invitation.user_id == user_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=at)
    )


async def revoke_workspace_invitations(
    session: AsyncSession, workspace_id: UUID, at: datetime
) -> int:
    """Withdraw every outstanding offer to join one workspace.

    Archiving counts active accounts, and an invited account is not one yet — so without this an
    archived workspace could still be joined by whoever is holding its invitation link.
    """
    result = await session.execute(
        update(Invitation)
        .where(
            Invitation.workspace_id == workspace_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=at)
        .returning(Invitation.id)
    )
    return len(result.scalars().all())


async def get_session_by_token(session: AsyncSession, token_hash: str) -> Session | None:
    """Unauthenticated lookup: the session token is the credential."""
    return (
        await session.execute(
            select(Session).where(Session.token_hash == token_hash, Session.revoked_at.is_(None))
        )
    ).scalar_one_or_none()


async def revoke_session_by_token(
    session: AsyncSession, token_hash: str, at: datetime
) -> Session | None:
    return (
        await session.execute(
            update(Session)
            .where(Session.token_hash == token_hash, Session.revoked_at.is_(None))
            .values(revoked_at=at)
            .returning(Session)
        )
    ).scalar_one_or_none()


async def revoke_session_by_id(
    session: AsyncSession, session_id: UUID, at: datetime
) -> Session | None:
    return (
        await session.execute(
            update(Session)
            .where(Session.id == session_id, Session.revoked_at.is_(None))
            .values(revoked_at=at)
            .returning(Session)
        )
    ).scalar_one_or_none()


async def revoke_sessions_for_user(session: AsyncSession, user_id: UUID, at: datetime) -> int:
    """AUTH-03: deactivation and password reset end every session the user still holds."""
    result = await session.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=at)
        .returning(Session.id)
    )
    return len(result.scalars().all())


async def revoke_all_sessions(session: AsyncSession, at: datetime) -> dict[UUID, int]:
    """Every live session in the deployment. Returns the count per workspace.

    Grouped by workspace because `audit_events` is workspace-scoped: a deployment holding more
    than one workspace gets a row in each rather than one row in an arbitrary one.
    """
    result = await session.execute(
        update(Session)
        .where(Session.revoked_at.is_(None))
        .values(revoked_at=at)
        .returning(Session.workspace_id)
    )
    counts: dict[UUID, int] = {}
    for workspace_id in result.scalars().all():
        counts[workspace_id] = counts.get(workspace_id, 0) + 1
    return counts


async def get_password_reset_by_token(
    session: AsyncSession, token_hash: str
) -> PasswordReset | None:
    """Unauthenticated lookup: the reset token is the credential."""
    return (
        await session.execute(select(PasswordReset).where(PasswordReset.token_hash == token_hash))
    ).scalar_one_or_none()


async def revoke_pending_password_resets(
    session: AsyncSession, user_id: UUID, at: datetime
) -> None:
    await session.execute(
        update(PasswordReset)
        .where(
            PasswordReset.user_id == user_id,
            PasswordReset.used_at.is_(None),
            PasswordReset.revoked_at.is_(None),
        )
        .values(revoked_at=at)
    )


async def workspace_ids(session: AsyncSession) -> list[UUID]:
    """Every workspace, for the periodic tasks that run on behalf of nobody."""
    rows = await session.execute(select(Workspace.id).order_by(Workspace.id))
    return list(rows.scalars().all())
