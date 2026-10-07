"""AUTH-01: workspace bootstrap and the audited break-glass procedure.

The professor account is a single point of failure in a one-professor workspace, so recovery and
transfer run from the host shell, never from the API (docs/runbooks/break-glass.md).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.clock import now
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.types import ActorKind, Role
from app.identity import models, service
from tests.factories import make_user, make_workspace

pytestmark = pytest.mark.module

PASSWORD = "a sufficiently long password"  # noqa: S105 - test credential


async def test_bootstrap_creates_the_workspace_and_its_professor(db: AsyncSession) -> None:
    result = await service.bootstrap_workspace(
        db, name="Vision Lab", prof_email="Head@example.edu", prof_display_name="Head of Lab"
    )

    assert result.workspace.name == "Vision Lab"
    assert result.user.role is Role.PROF
    assert result.user.state is models.UserState.INVITED
    user = await service.accept_invitation(db, token=result.token, password=PASSWORD)
    assert user.state is models.UserState.ACTIVE
    assert (await service.login(db, email="head@example.edu", password=PASSWORD)).user.id == user.id


async def test_bootstrap_records_the_owner_and_a_system_audit_row(db: AsyncSession) -> None:
    result = await service.bootstrap_workspace(
        db, name="Vision Lab", prof_email="head@example.edu", prof_display_name="Head of Lab"
    )

    workspace = (
        await db.execute(select(models.Workspace).where(models.Workspace.id == result.workspace.id))
    ).scalar_one()
    assert workspace.owner_id == result.user.id

    event = (
        await db.execute(select(AuditEvent).where(AuditEvent.action == "workspace.bootstrapped"))
    ).scalar_one()
    assert event.actor_kind is ActorKind.SYSTEM
    assert event.actor_id is None


async def test_bootstrap_refuses_an_email_that_already_exists(
    db: AsyncSession, student_a: models.User
) -> None:
    with pytest.raises(ConflictError):
        await service.bootstrap_workspace(
            db, name="Second Lab", prof_email=student_a.email, prof_display_name="Someone"
        )


async def test_recovery_issues_a_short_lived_single_use_link(
    db: AsyncSession, prof: models.User
) -> None:
    link = await service.recover_professor(db, email=prof.email)

    assert link.user_id == prof.id
    assert link.expires_at <= now() + timedelta(minutes=15)
    user = await service.reset_password(db, token=link.token, password=PASSWORD)
    assert user.id == prof.id
    with pytest.raises(ValidationError):
        await service.reset_password(db, token=link.token, password=PASSWORD)


async def test_recovery_restores_a_locked_out_professor(
    db: AsyncSession, prof_scope: object, workspace: models.Workspace
) -> None:
    # The professor was demoted or deactivated by mistake; break-glass is what undoes that.
    locked_out = await make_user(db, workspace, role=Role.STUDENT, email="head@example.edu")
    locked_out.state = models.UserState.DEACTIVATED
    await db.flush()

    link = await service.recover_professor(db, email="head@example.edu")

    restored = (
        await db.execute(select(models.User).where(models.User.id == locked_out.id))
    ).scalar_one()
    assert restored.role is Role.PROF
    assert restored.state is models.UserState.ACTIVE
    assert restored.deactivated_at is None
    assert (await service.reset_password(db, token=link.token, password=PASSWORD)).id == restored.id


async def test_recovery_is_audited_as_a_system_action(db: AsyncSession, prof: models.User) -> None:
    await service.recover_professor(db, email=prof.email)

    event = (
        await db.execute(select(AuditEvent).where(AuditEvent.action == "identity.break_glass"))
    ).scalar_one()
    assert event.actor_kind is ActorKind.SYSTEM
    assert event.target_id == prof.id


async def test_recovery_of_an_unknown_address_fails_loudly(db: AsyncSession) -> None:
    # An operator at a shell deserves the real reason; this path cannot enumerate anything.
    with pytest.raises(NotFoundError):
        await service.recover_professor(db, email="nobody@example.edu")


async def test_transfer_hands_the_workspace_to_a_new_professor(
    db: AsyncSession, prof: models.User, student_a: models.User
) -> None:
    link = await service.transfer_professor(db, from_email=prof.email, to_email=student_a.email)

    successor = (
        await db.execute(select(models.User).where(models.User.id == student_a.id))
    ).scalar_one()
    predecessor = (
        await db.execute(select(models.User).where(models.User.id == prof.id))
    ).scalar_one()
    assert successor.role is Role.PROF
    assert predecessor.state is models.UserState.DEACTIVATED
    assert link.user_id == successor.id


async def test_transfer_ends_the_previous_professors_sessions(
    db: AsyncSession, prof: models.User, student_a: models.User
) -> None:
    from tests.factories import DEFAULT_PASSWORD

    signed_in = await service.login(db, email=prof.email, password=DEFAULT_PASSWORD)

    await service.transfer_professor(db, from_email=prof.email, to_email=student_a.email)

    assert await service.resolve_session(db, token=signed_in.token) is None


async def test_transfer_can_name_someone_who_has_no_account_yet(
    db: AsyncSession, prof: models.User
) -> None:
    link = await service.transfer_professor(
        db, from_email=prof.email, to_email="successor@example.edu", display_name="Successor"
    )

    user = await service.reset_password(db, token=link.token, password=PASSWORD)
    assert user.email == "successor@example.edu"
    assert user.role is Role.PROF
    assert (await service.login(db, email=user.email, password=PASSWORD)).user.id == user.id


async def test_transfer_to_the_same_account_is_rejected(
    db: AsyncSession, prof: models.User
) -> None:
    with pytest.raises(ValidationError):
        await service.transfer_professor(db, from_email=prof.email, to_email=prof.email)


async def test_transfer_refuses_an_account_in_another_workspace(
    db: AsyncSession, prof: models.User
) -> None:
    other = await make_workspace(db, name="Another Lab")
    outsider = await make_user(db, other, email="outsider@example.edu")

    with pytest.raises(ConflictError):
        await service.transfer_professor(db, from_email=prof.email, to_email=outsider.email)


async def test_transfer_audits_the_state_the_predecessor_actually_had(
    db: AsyncSession, prof: models.User, student_a: models.User
) -> None:
    # The outgoing professor may already be deactivated: that is often why a transfer is needed.
    prof.state = models.UserState.DEACTIVATED
    await db.flush()

    await service.transfer_professor(db, from_email=prof.email, to_email=student_a.email)

    event = (
        await db.execute(
            select(AuditEvent).where(
                AuditEvent.action == "identity.break_glass_transfer",
                AuditEvent.target_id == prof.id,
            )
        )
    ).scalar_one()
    assert event.before == {"state": "deactivated"}


# ---------------------------------------------------------------- transfer and membership


async def _member_workspace_ids(db: AsyncSession, user_id: object) -> set[object]:
    rows = await db.execute(
        select(models.WorkspaceMember.workspace_id).where(models.WorkspaceMember.user_id == user_id)
    )
    return set(rows.scalars().all())


async def test_a_new_successor_belongs_to_the_workspace_they_were_handed(
    db: AsyncSession, workspace: models.Workspace, prof: models.User
) -> None:
    """Belonging is the membership row: without it the successor is missing from the roll."""
    link = await service.transfer_professor(
        db, from_email=prof.email, to_email="successor@example.edu"
    )

    assert workspace.id in await _member_workspace_ids(db, link.user_id)
    successor = await db.get(models.User, link.user_id)
    assert successor is not None
    scope = await service.scope_for(db, successor)
    listed = await service.list_users(db, scope)
    assert link.user_id in {user.id for user in listed.items}


async def test_the_successor_takes_over_every_workspace_the_predecessor_belonged_to(
    db: AsyncSession, workspace: models.Workspace, prof: models.User, student_a: models.User
) -> None:
    second = await make_workspace(db, name="Second Lab")
    db.add(models.WorkspaceMember(workspace_id=second.id, user_id=prof.id))
    await db.flush()

    await service.transfer_professor(db, from_email=prof.email, to_email=student_a.email)

    assert await _member_workspace_ids(db, student_a.id) == {workspace.id, second.id}
    assert await _member_workspace_ids(db, prof.id) == set()


async def test_after_a_transfer_the_successor_is_the_professor_the_guard_counts(
    db: AsyncSession, prof: models.User
) -> None:
    """The predecessor no longer counts, and the successor does: the successor is now the last."""
    link = await service.transfer_professor(
        db, from_email=prof.email, to_email="successor@example.edu"
    )
    await service.reset_password(db, token=link.token, password=PASSWORD)

    with pytest.raises(ConflictError):
        await service.deactivate_professor(db, email="successor@example.edu")


async def test_transfer_revokes_the_predecessors_open_invitations(
    db: AsyncSession, workspace: models.Workspace, prof: models.User, student_a: models.User
) -> None:
    pending = models.Invitation(
        workspace_id=workspace.id,
        user_id=prof.id,
        email=prof.email,
        role=Role.PROF,
        token_hash="pending-invitation-digest",
        expires_at=now() + timedelta(days=7),
    )
    db.add(pending)
    await db.flush()

    await service.transfer_professor(db, from_email=prof.email, to_email=student_a.email)

    await db.refresh(pending)
    assert pending.revoked_at is not None


async def test_the_last_professor_guard_counts_members_not_the_anchor(
    db: AsyncSession, workspace: models.Workspace, prof: models.User
) -> None:
    """A professor working elsewhere still belongs here, so demoting the other one is allowed."""
    elsewhere = await make_workspace(db, name="Elsewhere Lab")
    colleague = await make_user(db, elsewhere, role=Role.PROF, email="colleague@example.edu")
    db.add(models.WorkspaceMember(workspace_id=workspace.id, user_id=colleague.id))
    await db.flush()

    demoted = await service.demote_professor(db, email=prof.email)

    assert demoted.role is Role.STUDENT
