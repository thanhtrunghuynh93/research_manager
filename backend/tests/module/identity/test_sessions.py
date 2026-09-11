"""AUTH-01/AUTH-03: login, session resolution, expiry, and logout."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.core.errors import UnauthenticatedError
from app.core.types import Role
from app.identity import models, security, service
from tests.factories import DEFAULT_PASSWORD, make_user

pytestmark = pytest.mark.module


async def test_login_returns_a_session_token_that_resolves_to_a_scope(
    db: AsyncSession, workspace: models.Workspace, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)

    context = await service.resolve_session(db, token=logged_in.token)
    assert context is not None
    assert context.scope.user_id == student_a.id
    assert context.scope.workspace_id == workspace.id
    assert context.scope.role is Role.STUDENT
    assert context.scope.access_epoch == workspace.access_epoch
    assert context.scope.project_ids == frozenset(), "memberships arrive with the projects module"


async def test_login_is_case_insensitive_on_the_email(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email.upper(), password=DEFAULT_PASSWORD)
    assert logged_in.user.id == student_a.id


async def test_the_wrong_password_is_rejected(db: AsyncSession, student_a: models.User) -> None:
    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=student_a.email, password="not the password")


async def test_an_unknown_email_is_rejected_without_revealing_anything(db: AsyncSession) -> None:
    with pytest.raises(UnauthenticatedError) as raised:
        await service.login(db, email="nobody@example.edu", password=DEFAULT_PASSWORD)
    assert "nobody@example.edu" not in raised.value.detail


async def test_an_invited_user_cannot_log_in_before_accepting(
    db: AsyncSession, workspace: models.Workspace
) -> None:
    await make_user(db, workspace, state=models.UserState.INVITED, password=None)
    invited = (
        await db.execute(select(models.User).where(models.User.state == models.UserState.INVITED))
    ).scalar_one()

    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=invited.email, password=DEFAULT_PASSWORD)


async def test_a_deactivated_user_cannot_log_in(
    db: AsyncSession, workspace: models.Workspace
) -> None:
    user = await make_user(db, workspace, state=models.UserState.DEACTIVATED)

    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=user.email, password=DEFAULT_PASSWORD)


async def test_logout_revokes_the_session(db: AsyncSession, student_a: models.User) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)

    await service.logout(db, token=logged_in.token)

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_logout_of_an_unknown_token_is_a_no_op(db: AsyncSession) -> None:
    await service.logout(db, token="not-a-real-token")


async def test_a_session_idle_for_more_than_twelve_hours_stops_resolving(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    await db.execute(
        update(models.Session)
        .where(models.Session.token_hash == security.hash_token(logged_in.token))
        .values(last_seen_at=now() - timedelta(hours=12, minutes=1))
    )

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_a_session_past_its_absolute_lifetime_stops_resolving(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    await db.execute(
        update(models.Session)
        .where(models.Session.token_hash == security.hash_token(logged_in.token))
        .values(expires_at=now() - timedelta(seconds=1))
    )

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_resolving_a_session_refreshes_last_seen_at_at_most_once_a_minute(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    token_hash = security.hash_token(logged_in.token)
    stale = now() - timedelta(minutes=5)
    await db.execute(
        update(models.Session)
        .where(models.Session.token_hash == token_hash)
        .values(last_seen_at=stale)
    )

    await service.resolve_session(db, token=logged_in.token)
    refreshed = (
        await db.execute(
            select(models.Session.last_seen_at).where(models.Session.token_hash == token_hash)
        )
    ).scalar_one()
    assert refreshed > stale

    await service.resolve_session(db, token=logged_in.token)
    unchanged = (
        await db.execute(
            select(models.Session.last_seen_at).where(models.Session.token_hash == token_hash)
        )
    ).scalar_one()
    assert unchanged == refreshed, "a second request within the minute writes nothing"


async def test_an_unknown_session_token_resolves_to_nothing(db: AsyncSession) -> None:
    assert await service.resolve_session(db, token="not-a-real-token") is None


async def test_only_the_digest_of_a_session_token_is_stored(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)

    stored = (await db.execute(select(models.Session.token_hash))).scalars().all()
    assert stored == [security.hash_token(logged_in.token)]
    assert logged_in.token not in stored
