"""PROJ-03/PROJ-06: milestones with retained baselines, tasks with partial completion."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import models, service

pytestmark = pytest.mark.module


async def _project(db: AsyncSession, scope: Scope) -> object:
    return await service.create_project(
        db, scope, title="Baseline evaluation", stage=models.ResearchStage.IMPLEMENTATION
    )


async def test_a_milestone_records_its_criteria_and_weight(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)

    milestone = await service.create_milestone(
        db,
        prof_scope,
        project.id,
        title="Reproduce the published baseline",
        success_criteria="Within 1 point of the reported score on the public split",
        weight=Decimal(3),
        target_on=date(2026, 10, 31),
    )

    assert milestone.status is models.MilestoneStatus.PLANNED
    assert milestone.weight == Decimal(3)
    assert milestone.revision_no == 1


async def test_changing_a_milestone_baseline_keeps_the_previous_version(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # PROJ-06: when milestone scope or weights change, retain and display the baseline version.
    project = await _project(db, prof_scope)
    milestone = await service.create_milestone(
        db, prof_scope, project.id, title="Reproduce the baseline", weight=Decimal(3)
    )

    await service.update_milestone(
        db,
        prof_scope,
        milestone.id,
        weight=Decimal(5),
        change_reason="Scope grew to cover the ablation study",
    )

    revisions = await service.list_milestone_revisions(db, prof_scope, milestone.id)
    assert [r.revision_no for r in revisions] == [1, 2]
    assert revisions[0].weight == Decimal(3), "the original weight is still readable"
    assert revisions[1].weight == Decimal(5)
    assert revisions[1].change_reason == "Scope grew to cover the ablation study"


async def test_a_baseline_change_without_a_reason_is_refused(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    milestone = await service.create_milestone(db, prof_scope, project.id, title="Reproduce")

    with pytest.raises(ValidationError):
        await service.update_milestone(db, prof_scope, milestone.id, weight=Decimal(5))


async def test_an_edit_that_changes_no_baseline_field_needs_no_reason(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    milestone = await service.create_milestone(db, prof_scope, project.id, title="Reproduce")

    updated = await service.update_milestone(
        db, prof_scope, milestone.id, description="Now with the ablation table"
    )

    assert updated.revision_no == 1
    assert len(await service.list_milestone_revisions(db, prof_scope, milestone.id)) == 1


async def test_a_retained_revision_cannot_be_rewritten(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    milestone = await service.create_milestone(db, prof_scope, project.id, title="Reproduce")

    with pytest.raises(Exception, match="immutable"):
        await db.execute(
            update(models.MilestoneRevision)
            .where(models.MilestoneRevision.milestone_id == milestone.id)
            .values(weight=Decimal(99))
        )
    await db.rollback()


async def test_project_progress_uses_milestone_weights_not_student_scores(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # PROJ-06: compute completion from professor-defined weights and accepted fractions.
    project = await _project(db, prof_scope)
    heavy = await service.create_milestone(
        db, prof_scope, project.id, title="Baseline", weight=Decimal(3)
    )
    light = await service.create_milestone(
        db, prof_scope, project.id, title="Write-up", weight=Decimal(1)
    )
    await service.update_milestone(
        db, prof_scope, heavy.id, accepted_completion=Decimal("1.00")
    )
    await service.update_milestone(
        db, prof_scope, light.id, accepted_completion=Decimal("0.50")
    )

    progress = await service.project_progress(db, prof_scope, project.id)

    # (3 x 1.00 + 1 x 0.50) / 4 = 0.875
    assert progress.milestone_count == 2
    assert progress.weighted_completion == Decimal("0.8750")


async def test_progress_is_unavailable_before_any_milestone_exists(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)

    progress = await service.project_progress(db, prof_scope, project.id)

    assert progress.milestone_count == 0
    assert progress.weighted_completion is None, "no milestones means no percentage to show"


async def test_progress_counts_overdue_milestones_and_open_blockers(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    await service.create_milestone(
        db,
        prof_scope,
        project.id,
        title="Late one",
        target_on=now().date() - timedelta(days=7),
    )
    task = await service.create_task(db, prof_scope, project.id, title="Get GPU time")
    await service.update_task(
        db, prof_scope, task.id, status=models.TaskStatus.BLOCKED, blocker="Cluster queue full"
    )

    progress = await service.project_progress(db, prof_scope, project.id)

    assert progress.overdue_milestones == 1
    assert progress.open_blockers == 1


async def test_a_task_links_to_a_milestone_in_the_same_project(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    other_project = await service.create_project(
        db, prof_scope, title="Other", stage=models.ResearchStage.THEORY
    )
    foreign = await service.create_milestone(db, prof_scope, other_project.id, title="Elsewhere")

    with pytest.raises(ValidationError):
        await service.create_task(
            db, prof_scope, project.id, title="Mislinked", milestone_id=foreign.id
        )


async def test_partial_completion_must_carry_a_reason(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # PROJ-03: completion may be partial and must include a reason and evidence.
    project = await _project(db, prof_scope)
    task = await service.create_task(db, prof_scope, project.id, title="Run the sweep")

    with pytest.raises(ValidationError):
        await service.update_task(db, prof_scope, task.id, completion_fraction=Decimal("0.50"))

    updated = await service.update_task(
        db,
        prof_scope,
        task.id,
        completion_fraction=Decimal("0.50"),
        completion_reason="Half the grid ran before the cluster went down",
    )
    assert updated.completion_fraction == Decimal("0.50")


async def test_a_student_reports_progress_on_their_own_task(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    task = await service.create_task(
        db, prof_scope, project.id, title="Run the sweep", assignee_id=student_a.id
    )
    scope = await identity_service.scope_for(db, student_a)

    updated = await service.update_task(
        db, scope, task.id, status=models.TaskStatus.BLOCKED, blocker="No GPU quota"
    )

    assert updated.blocker == "No GPU quota"


async def test_a_student_cannot_rewrite_the_plan(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    task = await service.create_task(
        db, prof_scope, project.id, title="Run the sweep", assignee_id=student_a.id
    )
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ValidationError):
        await service.update_task(db, scope, task.id, effort_weight=Decimal(99))


async def test_a_student_cannot_touch_another_students_task(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await service.add_member(db, prof_scope, project.id, student_id=student_b.id)
    task = await service.create_task(
        db, prof_scope, project.id, title="Run the sweep", assignee_id=student_b.id
    )
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(NotFoundError):
        await service.update_task(db, scope, task.id, status=models.TaskStatus.DONE)


async def test_a_student_cannot_create_a_milestone(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ForbiddenError):
        await service.create_milestone(db, scope, project.id, title="Mine now")


async def test_a_dated_decision_explains_a_change_of_direction(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    await service.record_decision(
        db,
        prof_scope,
        project.id,
        decision="Drop the transformer baseline",
        rationale="Three weeks of tuning did not reach the reported score; the CNN baseline does.",
        decided_on=date(2026, 9, 10),
    )

    scope = await identity_service.scope_for(db, student_a)
    decisions = await service.list_decisions(db, scope, project.id)
    assert [d.decision for d in decisions] == ["Drop the transformer baseline"]
    assert decisions[0].decided_on == date(2026, 9, 10)


async def test_milestones_are_invisible_outside_the_project(
    db: AsyncSession, prof_scope: Scope, student_a_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    await service.create_milestone(db, prof_scope, project.id, title="Private to the project")

    with pytest.raises(NotFoundError):
        await service.list_milestones(db, student_a_scope, project.id)
