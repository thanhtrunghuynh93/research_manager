"""PROJ-04/AC-18: the plan a week is assessed against, frozen before the week begins.

The baseline exists so that "did you do what you agreed to do" has a fixed answer. It freezes at the
start of the period from the previous report's next-week plan. When there is no such plan — a new
member, a missing or late report, a paused project — the baseline is empty and commitment
completion is unavailable for that week (ASSESS-05).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import models, service
from app.reporting import service as reporting_service
from tests.factories import make_project

pytestmark = pytest.mark.module

PLAN = [
    {"planned_outcome": "Baseline runs end to end", "weight": 2, "acceptance_criteria": "One log"},
    {"planned_outcome": "Write the method section", "weight": 1, "acceptance_criteria": "Draft"},
]


async def _membership(
    db: AsyncSession, scope: Scope, student: identity_models.User
) -> tuple[object, object]:
    """A membership and a real reporting period for it, since a baseline belongs to a week."""
    await reporting_service.configure_calendar(
        db,
        scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await make_project(db, scope)
    membership = await service.add_member(
        db, scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, scope, through=date(2026, 9, 20)))[0]
    return period, membership


async def test_a_frozen_baseline_records_the_plan_and_its_source(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, membership = await _membership(db, prof_scope, student_a)

    baseline = await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )

    assert baseline.state is models.BaselineState.FROZEN
    assert baseline.version_no == 1
    assert [item.planned_outcome for item in baseline.items] == [
        "Baseline runs end to end",
        "Write the method section",
    ]
    assert baseline.frozen_at is not None


async def test_no_plan_at_the_freeze_point_gives_an_empty_baseline(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-18: a new member, a missing report, or a paused project leaves nothing to freeze.
    period, membership = await _membership(db, prof_scope, student_a)

    baseline = await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=[]
    )

    assert baseline.state is models.BaselineState.EMPTY
    assert baseline.items == []


async def test_commitment_completion_is_unavailable_without_a_frozen_plan(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-05: with no frozen baseline there is nothing to measure against.
    period, membership = await _membership(db, prof_scope, student_a)
    await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=[]
    )

    assert (
        await service.effective_baseline(
            db, prof_scope, membership_id=membership.id, period_id=period.id
        )
        is None
    )


async def test_only_one_baseline_is_in_effect_at_a_time(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # The invariant from requirements section 9, enforced by a partial unique index.
    from sqlalchemy.exc import IntegrityError

    period, membership = await _membership(db, prof_scope, student_a)
    await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )

    db.add(
        models.PlanBaseline(
            workspace_id=prof_scope.workspace_id,
            membership_id=membership.id,
            period_id=period.id,
            version_no=99,
            state=models.BaselineState.FROZEN,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_a_frozen_plan_cannot_be_edited_in_place(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, membership = await _membership(db, prof_scope, student_a)
    baseline = await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )

    with pytest.raises(DBAPIError, match="immutable|frozen"):
        await db.execute(
            update(models.PlanBaselineItem)
            .where(models.PlanBaselineItem.baseline_id == baseline.id)
            .values(weight=Decimal(99))
        )
    await db.rollback()


async def test_only_the_professor_freezes_a_baseline(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, membership = await _membership(db, prof_scope, student_a)
    scope = await _student_scope(db, student_a)

    with pytest.raises(ForbiddenError):
        await service.freeze_baseline(
            db, scope, membership_id=membership.id, period_id=period.id, items=PLAN
        )


async def _student_scope(db: AsyncSession, student: identity_models.User) -> Scope:
    from app.identity import service as identity_service

    return await identity_service.scope_for(db, student)


async def test_joining_a_project_does_not_expose_a_co_members_plan(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """The bound on PROJ-07: joining discloses the project, never another student's record.

    `plan_baseline_visible_to` filters on the caller's own membership rather than on the project,
    which is what makes this hold — and it is the assertion worth pinning, because every other
    project-shaped record a joiner gains is deliberately shared.
    """
    period, theirs = await _membership(db, prof_scope, student_a)
    await service.freeze_baseline(
        db, prof_scope, membership_id=theirs.id, period_id=period.id, items=PLAN
    )
    await service.update_project(db, prof_scope, theirs.project_id, open_to_join=True)

    joiner = await identity_service.scope_for(db, student_b)
    await service.join_project(db, joiner, theirs.project_id)

    joiner = await identity_service.scope_for(db, student_b)
    assert (
        await service.list_baselines(db, joiner, membership_id=theirs.id, period_id=period.id)
    ) == []
    # And the professor still sees it, so the empty list above is the policy and not an empty table.
    assert (
        await service.list_baselines(db, prof_scope, membership_id=theirs.id, period_id=period.id)
    ) != []
