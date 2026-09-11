"""AUTH-01: invitation-based enrollment. Only the professor invites; tokens are single use."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, ForbiddenError, ValidationError
from app.core.types import Role
from app.identity import models, security, service

pytestmark = pytest.mark.module

PASSWORD = "a sufficiently long password"  # noqa: S105 - test credential


async def test_invitation_creates_an_invited_user_and_a_single_use_token(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(
        db, prof_scope, email="New.Student@Example.edu", display_name="New Student"
    )

    assert invited.invitation.email == "new.student@example.edu", "address is normalised"
    assert invited.invitation.role is Role.STUDENT
    assert invited.token and invited.token not in repr(invited.invitation)

    user = (
        await db.execute(select(models.User).where(models.User.email == "new.student@example.edu"))
    ).scalar_one()
    assert user.state is models.UserState.INVITED
    assert user.password_hash is None, "the password is set by the student, not the professor"


async def test_accepting_an_invitation_activates_the_account(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")

    user = await service.accept_invitation(db, token=invited.token, password=PASSWORD)

    assert user.state is models.UserState.ACTIVE
    logged_in = await service.login(db, email="new@example.edu", password=PASSWORD)
    assert logged_in.user.id == user.id


async def test_an_invitation_token_cannot_be_used_twice(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")
    await service.accept_invitation(db, token=invited.token, password=PASSWORD)

    with pytest.raises(ValidationError):
        await service.accept_invitation(db, token=invited.token, password="another password 123")


async def test_an_expired_invitation_is_rejected(db: AsyncSession, prof_scope: Scope) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")
    await db.execute(
        update(models.Invitation)
        .where(models.Invitation.id == invited.invitation.id)
        .values(expires_at=now() - timedelta(minutes=1))
    )

    with pytest.raises(ValidationError):
        await service.accept_invitation(db, token=invited.token, password=PASSWORD)


async def test_an_unknown_invitation_token_is_rejected(db: AsyncSession) -> None:
    with pytest.raises(ValidationError):
        await service.accept_invitation(db, token="not-a-real-token", password=PASSWORD)


async def test_reinviting_revokes_the_previous_token(db: AsyncSession, prof_scope: Scope) -> None:
    first = await service.invite_user(db, prof_scope, email="new@example.edu")
    second = await service.invite_user(db, prof_scope, email="new@example.edu")

    with pytest.raises(ValidationError):
        await service.accept_invitation(db, token=first.token, password=PASSWORD)
    user = await service.accept_invitation(db, token=second.token, password=PASSWORD)
    assert user.state is models.UserState.ACTIVE


async def test_inviting_an_active_user_conflicts(
    db: AsyncSession, prof_scope: Scope, student_a: models.User
) -> None:
    with pytest.raises(ConflictError):
        await service.invite_user(db, prof_scope, email=student_a.email)


async def test_a_student_cannot_invite_anyone(db: AsyncSession, student_a_scope: Scope) -> None:
    with pytest.raises(ForbiddenError):
        await service.invite_user(db, student_a_scope, email="new@example.edu")


async def test_the_professor_can_invite_a_second_professor(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(
        db, prof_scope, email="colleague@example.edu", role=Role.PROF
    )
    assert invited.invitation.role is Role.PROF


async def test_invitation_and_acceptance_are_audited(db: AsyncSession, prof_scope: Scope) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")
    await service.accept_invitation(db, token=invited.token, password=PASSWORD)

    actions = (
        await db.execute(select(AuditEvent.action).order_by(AuditEvent.occurred_at))
    ).scalars()
    assert {"user.invited", "invitation.accepted"} <= set(actions)


async def test_a_weak_password_cannot_activate_an_account(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")

    with pytest.raises(ValidationError):
        await service.accept_invitation(db, token=invited.token, password="short")

    # the invitation survives a rejected attempt so the student can try again
    user = await service.accept_invitation(db, token=invited.token, password=PASSWORD)
    assert user.state is models.UserState.ACTIVE


async def test_only_the_digest_of_an_invitation_token_is_stored(
    db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")

    row = (
        await db.execute(
            select(models.Invitation).where(models.Invitation.id == invited.invitation.id)
        )
    ).scalar_one()
    assert row.token_hash == security.hash_token(invited.token)
    assert invited.token not in row.token_hash
