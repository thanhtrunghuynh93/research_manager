"""PROJ-01/PROJ-02: project records, membership, and what membership makes visible."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import models, service

pytestmark = pytest.mark.module


async def _project(db: AsyncSession, scope: Scope, title: str = "Baseline evaluation") -> object:
    return await service.create_project(
        db,
        scope,
        title=title,
        description="Evaluate the published baselines on our dataset.",
        stage=models.ResearchStage.IMPLEMENTATION,
    )


async def test_the_professor_creates_a_project_with_its_research_record(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await service.create_project(
        db,
        prof_scope,
        title="Baseline evaluation",
        description="Evaluate the published baselines on our dataset.",
        stage=models.ResearchStage.IMPLEMENTATION,
        research_questions=["Does the reported gain hold on our data?"],
        intended_contributions=["A reproducible evaluation harness"],
        start_on=date(2026, 9, 14),
        target_on=date(2026, 12, 14),
        venue_target="ICLR 2027",
    )

    assert project.status is models.ProjectStatus.PROPOSED, "a new project starts as proposed"
    assert project.research_questions == ["Does the reported gain hold on our data?"]
    assert project.venue_target == "ICLR 2027"


async def test_a_student_cannot_create_a_project(db: AsyncSession, student_a_scope: Scope) -> None:
    with pytest.raises(ForbiddenError):
        await _project(db, student_a_scope)


async def test_a_student_sees_only_the_projects_they_belong_to(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    joined = await _project(db, prof_scope, title="Joined")
    await _project(db, prof_scope, title="Not joined")
    await service.add_member(db, prof_scope, joined.id, student_id=student_a.id)

    scope = await identity_service.scope_for(db, student_a)
    page = await service.list_projects(db, scope)

    assert [p.title for p in page.items] == ["Joined"]


async def test_membership_is_what_fills_a_students_scope(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    scope = await identity_service.scope_for(db, student_a)

    assert scope.project_ids == frozenset({project.id})


async def test_ending_a_membership_removes_access_and_advances_the_epoch(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    # AUTH-03: removing a membership invalidates subsequent access and cached answers.
    project = await _project(db, prof_scope)
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    before = (
        await db.execute(
            select(identity_models.Workspace.access_epoch).where(
                identity_models.Workspace.id == workspace.id
            )
        )
    ).scalar_one()

    await service.end_membership(db, prof_scope, membership.id)

    scope = await identity_service.scope_for(db, student_a)
    assert scope.project_ids == frozenset(), "removal takes effect now, not tomorrow"
    assert scope.access_epoch > before


async def test_a_departure_dated_in_the_future_keeps_access_until_then(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    later = now().date() + timedelta(days=30)

    await service.end_membership(db, prof_scope, membership.id, left_on=later)

    scope = await identity_service.scope_for(db, student_a)
    assert scope.project_ids == frozenset({project.id})


async def test_ending_a_membership_keeps_the_history(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # PROJ-02: retain membership history instead of deleting it when a student leaves.
    project = await _project(db, prof_scope)
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    ended = await service.end_membership(db, prof_scope, membership.id, left_on=date(2026, 10, 1))

    assert ended.left_on == date(2026, 10, 1)
    rows = (
        (
            await db.execute(
                select(models.ProjectMembership).where(models.ProjectMembership.id == membership.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the row stays; only left_on is written"


async def test_the_same_student_cannot_hold_two_active_memberships(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    with pytest.raises(ConflictError):
        await service.add_member(db, prof_scope, project.id, student_id=student_a.id)


async def test_a_student_can_rejoin_after_leaving(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    first = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await service.end_membership(db, prof_scope, first.id, left_on=date(2026, 10, 1))

    second = await service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 11, 1)
    )

    assert second.id != first.id
    scope = await identity_service.scope_for(db, student_a)
    assert scope.project_ids == frozenset({project.id})


async def test_a_membership_cannot_reach_into_another_workspace(
    db: AsyncSession, prof_scope: Scope
) -> None:
    from tests.factories import make_user, make_workspace

    project = await _project(db, prof_scope)
    other = await make_workspace(db, name="Another Lab")
    outsider = await make_user(db, other)

    with pytest.raises(NotFoundError):
        await service.add_member(db, prof_scope, project.id, student_id=outsider.id)


async def test_the_professor_cannot_be_enrolled_as_a_student(
    db: AsyncSession, prof_scope: Scope, prof: identity_models.User
) -> None:
    project = await _project(db, prof_scope)

    with pytest.raises(ConflictError):
        await service.add_member(db, prof_scope, project.id, student_id=prof.id)


async def test_a_student_cannot_enrol_themselves(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    project = await _project(db, prof_scope)

    with pytest.raises(ForbiddenError):
        await service.add_member(db, student_a_scope, project.id, student_id=student_a.id)


async def test_project_members_can_see_each_other(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # UI-03: the project workspace lists its members to the people working on it.
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await service.add_member(db, prof_scope, project.id, student_id=student_b.id)

    scope = await identity_service.scope_for(db, student_a)
    members = await service.list_members(db, scope, project.id)

    assert {m.student_id for m in members} == {student_a.id, student_b.id}


async def test_a_non_member_cannot_read_the_project(
    db: AsyncSession, prof_scope: Scope, student_a_scope: Scope
) -> None:
    project = await _project(db, prof_scope)

    with pytest.raises(NotFoundError):
        await service.get_project(db, student_a_scope, project.id)


async def test_the_status_moves_through_the_documented_states(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)

    for status in (
        models.ProjectStatus.ACTIVE,
        models.ProjectStatus.PAUSED,
        models.ProjectStatus.COMPLETED,
        models.ProjectStatus.ARCHIVED,
    ):
        updated = await service.update_project(db, prof_scope, project.id, status=status)
        assert updated.status is status


async def test_project_and_membership_changes_are_audited(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    membership = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await service.end_membership(db, prof_scope, membership.id, left_on=date(2026, 10, 1))

    actions = set((await db.execute(select(AuditEvent.action))).scalars().all())
    assert {"project.created", "membership.added", "membership.ended"} <= actions
