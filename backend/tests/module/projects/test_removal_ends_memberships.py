"""ADR 0011: removing a student ends every membership, in the removing professor's transaction.

Deactivating alone was never enough. Obligations derive from memberships (REP-01) and nothing in
that path filters on user state, so a student who only lost their login kept accruing weekly
obligations and the reminders attached to them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import models, service

pytestmark = pytest.mark.module


async def _project(db: AsyncSession, scope: Scope, title: str) -> object:
    return await service.create_project(
        db,
        scope,
        title=title,
        description="Evaluate the published baselines on our dataset.",
        stage=models.ResearchStage.IMPLEMENTATION,
    )


async def test_removal_ends_every_membership_the_student_still_holds(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    first = await _project(db, prof_scope, "Baseline evaluation")
    second = await _project(db, prof_scope, "Theory")
    await service.add_member(db, prof_scope, first.id, student_id=student_a.id)
    await service.add_member(db, prof_scope, second.id, student_id=student_a.id)

    await identity_service.remove_student(db, prof_scope, student_a.id)

    rows = (
        (
            await db.execute(
                select(models.ProjectMembership).where(
                    models.ProjectMembership.student_id == student_a.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(row.left_on is not None for row in rows), "an open membership still owes reports"


async def test_removal_keeps_the_membership_rows_as_history(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """PROJ-02: the row is kept rather than deleted, so past work stays attributable."""
    project = await _project(db, prof_scope, "Baseline evaluation")
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    await identity_service.remove_student(db, prof_scope, student_a.id)

    row = await db.get(models.ProjectMembership, membership.id)
    assert row is not None
    assert row.joined_on == membership.joined_on


async def test_removal_audits_each_membership_it_ends(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope, "Baseline evaluation")
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    await identity_service.remove_student(db, prof_scope, student_a.id)

    event = (
        await db.execute(
            select(AuditEvent).where(
                AuditEvent.target_id == membership.id,
                AuditEvent.action == "membership.ended",
            )
        )
    ).scalar_one()
    assert event.after["reason"] == "user.removed"
    assert event.actor_id == prof_scope.user_id


async def test_a_membership_already_ended_is_left_alone(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope, "Baseline evaluation")
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    ended = await service.end_membership(db, prof_scope, membership.id)

    await identity_service.remove_student(db, prof_scope, student_a.id)

    row = await db.get(models.ProjectMembership, membership.id)
    assert row is not None
    assert row.left_on == ended.left_on, "removal must not restamp a membership that already ended"


async def test_suspending_a_student_leaves_their_memberships_open(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Deactivation is suspension and `reactivate_user` undoes it, so the roll is untouched."""
    project = await _project(db, prof_scope, "Baseline evaluation")
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    await identity_service.deactivate_user(db, prof_scope, student_a.id)

    row = await db.get(models.ProjectMembership, membership.id)
    assert row is not None
    assert row.left_on is None
