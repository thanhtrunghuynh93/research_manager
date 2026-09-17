"""PROJ-01/PROJ-02: project records, membership, and what membership makes visible."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.types import Role
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


async def test_a_student_starts_their_own_project_and_is_on_it(
    db: AsyncSession, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    # PROJ-07. Active rather than proposed, because there is no second party to activate it, and a
    # proposed project derives no obligation — the student would have a page and no weekly report.
    project = await _project(db, student_a_scope, title="My own project")

    assert project.status is models.ProjectStatus.ACTIVE
    assert project.created_by == student_a.id

    scope = await identity_service.scope_for(db, student_a)
    assert project.id in scope.project_ids, "the creator is enrolled, or nothing derives from it"


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


async def test_a_student_cannot_enrol_another_student(
    db: AsyncSession, prof_scope: Scope, student_b: identity_models.User, student_a_scope: Scope
) -> None:
    # PROJ-07 opened joining, not assigning: a student speaks for themselves and no one else.
    project = await _project(db, prof_scope)

    with pytest.raises(ForbiddenError):
        await service.add_member(db, student_a_scope, project.id, student_id=student_b.id)


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


# ------------------------------------------------------------------ PROJ-07: self-service


async def _open_project(db: AsyncSession, prof_scope: Scope, title: str = "Open project") -> object:
    project = await _project(db, prof_scope, title=title)
    return await service.update_project(
        db,
        prof_scope,
        project.id,
        status=models.ProjectStatus.ACTIVE,
        open_to_join=True,
    )


async def test_the_joinable_list_offers_only_what_the_professor_opened(
    db: AsyncSession, prof_scope: Scope, student_a_scope: Scope
) -> None:
    opened = await _open_project(db, prof_scope, title="Open")
    await _project(db, prof_scope, title="Closed")
    archived = await _open_project(db, prof_scope, title="Archived")
    await service.update_project(db, prof_scope, archived.id, status=models.ProjectStatus.ARCHIVED)

    offered = await service.list_joinable(db, student_a_scope)

    assert [p.title for p in offered] == ["Open"]
    assert offered[0].id == opened.id


async def test_a_project_already_joined_is_not_offered_again(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _open_project(db, prof_scope)
    await service.join_project(db, await identity_service.scope_for(db, student_a), project.id)

    scope = await identity_service.scope_for(db, student_a)
    assert await service.list_joinable(db, scope) == []


async def test_a_student_joins_an_open_project_and_can_then_read_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    project = await _open_project(db, prof_scope)

    with pytest.raises(NotFoundError):
        await service.get_project(db, student_a_scope, project.id)

    membership = await service.join_project(db, student_a_scope, project.id)
    assert membership.origin is models.MembershipOrigin.SELF_JOINED

    scope = await identity_service.scope_for(db, student_a)
    assert (await service.get_project(db, scope, project.id)).id == project.id


async def test_a_closed_project_cannot_be_joined(
    db: AsyncSession, prof_scope: Scope, student_a_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    await service.update_project(db, prof_scope, project.id, status=models.ProjectStatus.ACTIVE)

    with pytest.raises(NotFoundError):
        await service.join_project(db, student_a_scope, project.id)


async def test_a_project_in_another_workspace_cannot_be_joined(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    from tests.factories import make_user, make_workspace

    other = await make_workspace(db, name="Another Lab")
    other_prof = await make_user(db, other, role=Role.PROF)
    elsewhere = await _open_project(
        db, await identity_service.scope_for(db, other_prof), title="Elsewhere"
    )

    assert await service.list_joinable(db, student_a_scope) == []
    with pytest.raises(NotFoundError):
        await service.join_project(db, student_a_scope, elsewhere.id)


async def test_joining_grants_the_projects_shared_records(
    db: AsyncSession, prof_scope: Scope, student_b: identity_models.User, student_b_scope: Scope
) -> None:
    """AUTH-02: a membership grants the project's own records — and it is a real grant, not a row.

    What it does *not* grant is another student's private record; that is asserted where the
    fixtures for it live (`test_plan_baselines.py`, `tests/authz/`).
    """
    project = await _open_project(db, prof_scope)
    await service.create_milestone(
        db, prof_scope, project.id, title="First ablation", target_on=date(2026, 10, 1)
    )

    await service.join_project(db, student_b_scope, project.id)

    scope = await identity_service.scope_for(db, student_b)
    assert [m.title for m in await service.list_milestones(db, scope, project.id)] == [
        "First ablation"
    ]


async def test_a_student_leaves_a_project_they_joined(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_a_scope: Scope,
) -> None:
    project = await _open_project(db, prof_scope)
    membership = await service.join_project(db, student_a_scope, project.id)

    epoch = await _epoch(db, workspace.id)
    scope = await identity_service.scope_for(db, student_a)
    ended = await service.end_membership(db, scope, membership.id)

    assert ended.left_on == now().date(), "PROJ-02 keeps the row rather than deleting it"
    assert await _epoch(db, workspace.id) > epoch, "AUTH-03: leaving revokes cached reads too"
    assert project.id not in (await identity_service.scope_for(db, student_a)).project_ids


async def test_joining_does_not_advance_the_epoch(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    prof_scope: Scope,
    student_a_scope: Scope,
) -> None:
    # Widening access cannot invalidate an answer computed under narrower access.
    project = await _open_project(db, prof_scope)
    epoch = await _epoch(db, workspace.id)

    await service.join_project(db, student_a_scope, project.id)

    assert await _epoch(db, workspace.id) == epoch


async def test_a_student_cannot_end_a_co_members_membership(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    student_b_scope: Scope,
) -> None:
    project = await _open_project(db, prof_scope)
    theirs = await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await service.join_project(db, student_b_scope, project.id)

    # After joining, the co-member's row *is* visible — UI-03 shows who else works on the project.
    # So this is the guard refusing the write, not the policy hiding the row.
    joiner = await identity_service.scope_for(db, student_b)
    with pytest.raises(ForbiddenError):
        await service.end_membership(db, joiner, theirs.id)


async def test_a_student_cannot_back_date_their_own_leave(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    # A back-dated leave would rewrite which weeks were owed. Only the professor may do that.
    project = await _open_project(db, prof_scope)
    membership = await service.join_project(db, student_a_scope, project.id)

    scope = await identity_service.scope_for(db, student_a)
    with pytest.raises(ValidationError):
        await service.end_membership(
            db, scope, membership.id, left_on=now().date() - timedelta(days=7)
        )


async def test_the_creator_edits_the_record_but_not_its_standing(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    project = await _project(db, student_a_scope, title="Mine")

    renamed = await service.update_project(db, student_a_scope, project.id, title="Renamed")
    assert renamed.title == "Renamed"

    for refused in (
        {"status": models.ProjectStatus.ARCHIVED},
        {"ai_restricted": True},
        {"open_to_join": True},
    ):
        with pytest.raises(ForbiddenError):
            await service.update_project(db, student_a_scope, project.id, **refused)


async def test_a_member_who_did_not_create_the_project_cannot_edit_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    scope = await identity_service.scope_for(db, student_a)
    with pytest.raises(ForbiddenError):
        await service.update_project(db, scope, project.id, title="Not theirs to rename")


async def test_the_creator_keeps_the_record_after_leaving_it(
    db: AsyncSession, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    # AUTH-07 outlives the membership, so `project_visible_to` has to grant the creator the row.
    project = await _project(db, student_a_scope, title="Mine")
    members = await service.list_members(db, student_a_scope, project.id)
    await service.end_membership(db, student_a_scope, members[0].id)

    scope = await identity_service.scope_for(db, student_a)
    assert project.id not in scope.project_ids
    assert (await service.update_project(db, scope, project.id, title="Still mine")).title == (
        "Still mine"
    )


async def _epoch(db: AsyncSession, workspace_id: object) -> int:
    return (
        await db.execute(
            select(identity_models.Workspace.access_epoch).where(
                identity_models.Workspace.id == workspace_id
            )
        )
    ).scalar_one()


# ------------------------------------------------------------------ PROJ-01: where the code lives


async def test_a_project_records_where_its_code_is(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    project = await service.create_project(
        db,
        student_a_scope,
        title="Spectral clustering",
        stage=models.ResearchStage.IMPLEMENTATION,
        repo_url="  https://github.com/lab/spectral  ",
    )

    assert project.repo_url == "https://github.com/lab/spectral", "trimmed, not stored as typed"


async def test_the_repository_link_is_optional_and_blank_means_absent(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    # Absent and empty must not be two states, or every screen decides for itself what "" means.
    omitted = await _project(db, student_a_scope, title="No repo")
    assert omitted.repo_url is None

    blanked = await service.update_project(db, student_a_scope, omitted.id, repo_url="   ")
    assert blanked.repo_url is None


async def test_the_creator_may_change_the_repository_link(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    project = await _project(db, student_a_scope, title="Mine")

    updated = await service.update_project(
        db, student_a_scope, project.id, repo_url="git@github.com:lab/mine.git"
    )

    assert updated.repo_url == "git@github.com:lab/mine.git"
