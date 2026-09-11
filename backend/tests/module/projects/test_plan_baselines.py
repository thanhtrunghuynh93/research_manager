"""PROJ-04/AC-18: the plan a week is assessed against, frozen before the week begins.

The baseline exists so that "did you do what you agreed to do" has a fixed answer. It freezes at the
start of the period from the previous report's next-week plan. When there is no such plan — a new
member, a missing or late report, a paused project — the baseline is empty, the student enters a
first plan in the current report, and commitment completion stays unavailable until the professor
accepts it (ASSESS-05).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError, ValidationError
from app.identity import models as identity_models
from app.projects import models, service
from app.reporting import service as reporting_service

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
    project = await service.create_project(
        db, scope, title="Baseline evaluation", stage="implementation"
    )
    await service.update_project(db, scope, project.id, status="active")
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


async def test_commitment_completion_is_unavailable_until_a_plan_is_accepted(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-05: with no frozen or accepted baseline there is nothing to measure against.
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


async def test_a_student_proposes_a_first_plan_and_the_professor_accepts_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, student_a_scope: Scope
) -> None:
    period, membership = await _membership(db, prof_scope, student_a)
    await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=[]
    )
    scope = await _student_scope(db, student_a)

    proposed = await service.propose_baseline(
        db, scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )
    assert proposed.state is models.BaselineState.PROPOSED
    assert (
        await service.effective_baseline(
            db, prof_scope, membership_id=membership.id, period_id=period.id
        )
        is None
    ), "a proposal is not yet a commitment"

    accepted = await service.accept_baseline(db, prof_scope, proposed.id)

    assert accepted.state is models.BaselineState.ACCEPTED
    assert accepted.approved_by == prof_scope.user_id
    assert accepted.approved_at is not None
    effective = await service.effective_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id
    )
    assert effective is not None and effective.id == accepted.id


async def test_a_student_cannot_accept_their_own_plan(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, membership = await _membership(db, prof_scope, student_a)
    await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=[]
    )
    scope = await _student_scope(db, student_a)
    proposed = await service.propose_baseline(
        db, scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )

    with pytest.raises(ForbiddenError):
        await service.accept_baseline(db, scope, proposed.id)


async def test_a_later_change_creates_a_version_and_keeps_the_original(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # PROJ-04: later changes require a new version, timestamp, and reason, and must not erase the
    # commitments originally missed.
    period, membership = await _membership(db, prof_scope, student_a)
    original = await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )

    revised = await service.supersede_baseline(
        db,
        prof_scope,
        original.id,
        items=[{"planned_outcome": "Baseline runs end to end", "weight": 3}],
        reason="Compute was unavailable; the write-up moved to next week",
    )

    assert revised.version_no == 2
    assert revised.change_reason.startswith("Compute was unavailable")
    history = await service.list_baselines(
        db, prof_scope, membership_id=membership.id, period_id=period.id
    )
    superseded = next(b for b in history if b.id == original.id)
    assert superseded.state is models.BaselineState.SUPERSEDED
    assert [item.planned_outcome for item in superseded.items] == [
        "Baseline runs end to end",
        "Write the method section",
    ], "the original commitments are still readable"


async def test_a_change_without_a_reason_is_refused(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, membership = await _membership(db, prof_scope, student_a)
    original = await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )

    with pytest.raises(ValidationError):
        await service.supersede_baseline(db, prof_scope, original.id, items=PLAN, reason="")


async def test_a_professor_approved_change_is_distinguishable_from_a_student_proposal(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # PROJ-04: professor-approved changes must be distinguishable from student-proposed changes.
    period, membership = await _membership(db, prof_scope, student_a)
    frozen = await service.freeze_baseline(
        db, prof_scope, membership_id=membership.id, period_id=period.id, items=PLAN
    )
    scope = await _student_scope(db, student_a)

    by_professor = await service.supersede_baseline(
        db, prof_scope, frozen.id, items=PLAN, reason="Scope agreed in the meeting"
    )
    by_student = await service.supersede_baseline(
        db, scope, by_professor.id, items=PLAN, reason="Cluster outage"
    )

    assert by_professor.state is models.BaselineState.FROZEN
    assert by_professor.approved_by == prof_scope.user_id
    assert by_student.state is models.BaselineState.PROPOSED
    assert by_student.proposed_by == student_a.id
    assert by_student.approved_by is None


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

    with pytest.raises(Exception, match="immutable|frozen"):
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
