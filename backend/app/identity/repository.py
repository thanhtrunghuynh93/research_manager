"""Queries over identity tables. No business rules here (docs/repo_layout.md §3.2).

Reads on behalf of a caller take a Scope and apply `visible_to`. The lookups used before a session
exists — login, invitation acceptance, password recovery — are marked as such: they authenticate the
caller rather than serve one, and every one of them is reached only through identity.service.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.pagination import decode_cursor, encode_cursor
from app.core.types import Role
from app.identity.models import (
    Invitation,
    PasswordReset,
    Session,
    User,
    UserState,
    Workspace,
)


async def get_workspace(session: AsyncSession, workspace_id: UUID) -> Workspace | None:
    return await session.get(Workspace, workspace_id)


async def access_epoch(session: AsyncSession, workspace_id: UUID) -> int:
    epoch = (
        await session.execute(select(Workspace.access_epoch).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    return epoch if epoch is not None else 0


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
    """Keyset pagination on the primary key, which is UUIDv7 and therefore in creation order."""
    statement = select(User).where(visible_to(scope, User)).order_by(User.id).limit(limit + 1)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        statement = statement.where(User.id > UUID(str(decoded["after"])))

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
    rows = await session.execute(
        select(User.id).where(
            User.workspace_id == workspace_id,
            User.role == Role.PROF,
            User.state == UserState.ACTIVE,
        )
    )
    return list(rows.scalars().all())


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
