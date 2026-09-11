"""AUTH-01: account recovery for every user through a verified out-of-band channel."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now
from app.core.errors import UnauthenticatedError, ValidationError
from app.identity import models, service
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module

NEW_PASSWORD = "a brand new long password"  # noqa: S105 - test credential


async def test_a_reset_token_sets_a_new_password(db: AsyncSession, student_a: models.User) -> None:
    requested = await service.request_password_reset(db, email=student_a.email)
    assert requested is not None

    await service.reset_password(db, token=requested.token, password=NEW_PASSWORD)

    logged_in = await service.login(db, email=student_a.email, password=NEW_PASSWORD)
    assert logged_in.user.id == student_a.id
    with pytest.raises(UnauthenticatedError):
        await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)


async def test_a_reset_revokes_every_existing_session(
    db: AsyncSession, student_a: models.User
) -> None:
    logged_in = await service.login(db, email=student_a.email, password=DEFAULT_PASSWORD)
    requested = await service.request_password_reset(db, email=student_a.email)
    assert requested is not None

    await service.reset_password(db, token=requested.token, password=NEW_PASSWORD)

    assert await service.resolve_session(db, token=logged_in.token) is None


async def test_a_reset_token_cannot_be_used_twice(db: AsyncSession, student_a: models.User) -> None:
    requested = await service.request_password_reset(db, email=student_a.email)
    assert requested is not None
    await service.reset_password(db, token=requested.token, password=NEW_PASSWORD)

    with pytest.raises(ValidationError):
        await service.reset_password(db, token=requested.token, password="yet another password")


async def test_an_expired_reset_token_is_rejected(db: AsyncSession, student_a: models.User) -> None:
    requested = await service.request_password_reset(db, email=student_a.email)
    assert requested is not None
    await db.execute(
        update(models.PasswordReset)
        .where(models.PasswordReset.user_id == student_a.id)
        .values(expires_at=now() - timedelta(seconds=1))
    )

    with pytest.raises(ValidationError):
        await service.reset_password(db, token=requested.token, password=NEW_PASSWORD)


async def test_requesting_a_reset_for_an_unknown_email_reveals_nothing(
    db: AsyncSession,
) -> None:
    assert await service.request_password_reset(db, email="nobody@example.edu") is None
    assert (await db.execute(select(models.PasswordReset))).first() is None


async def test_a_deactivated_user_cannot_reset_their_password(
    db: AsyncSession, prof_scope: object, student_a: models.User
) -> None:
    from app.core.authz import Scope

    assert isinstance(prof_scope, Scope)
    await service.deactivate_user(db, prof_scope, student_a.id)

    assert await service.request_password_reset(db, email=student_a.email) is None


async def test_a_weak_replacement_password_is_rejected(
    db: AsyncSession, student_a: models.User
) -> None:
    requested = await service.request_password_reset(db, email=student_a.email)
    assert requested is not None

    with pytest.raises(ValidationError):
        await service.reset_password(db, token=requested.token, password="short")

    # the token survives so the user can retry with a longer password
    user = await service.reset_password(db, token=requested.token, password=NEW_PASSWORD)
    assert user.id == student_a.id


async def test_requesting_a_second_reset_revokes_the_first_token(
    db: AsyncSession, student_a: models.User
) -> None:
    first = await service.request_password_reset(db, email=student_a.email)
    second = await service.request_password_reset(db, email=student_a.email)
    assert first is not None and second is not None

    with pytest.raises(ValidationError):
        await service.reset_password(db, token=first.token, password=NEW_PASSWORD)
    user = await service.reset_password(db, token=second.token, password=NEW_PASSWORD)
    assert user.id == student_a.id
