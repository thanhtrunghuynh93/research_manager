"""ASSESS-05 and ASSESS-06: the two numbers beside the ratings, and what they are made of.

Both shipped detached from their inputs. Commitment completion was computed with every accepted
fraction hardcoded to zero, so a student who finished everything they agreed to was shown 0% every
week — and the rating prompt was never even given the baseline to judge against. Coverage was
computed over the dimensions the model happened to return, so a response that answered three of
four dimensions reported 100% coverage and high confidence.

Neither failure looks like a failure on screen, which is what makes them worth a test each.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import DimensionRating, PlanItemAssessment, RubricOutput
from app.assessment import service
from app.assessment.metrics import Confidence
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module

PLAN = [
    {"planned_outcome": "Baseline runs end to end", "weight": 3, "acceptance_criteria": "One log"},
    {"planned_outcome": "Write the method section", "weight": 1, "acceptance_criteria": "Draft"},
]


async def _week(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User, *, plan: list | None = PLAN
) -> tuple[object, object, object]:
    """A submitted week, with a frozen baseline unless `plan` is None."""
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    membership = await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    if plan is not None:
        await projects_service.freeze_baseline(
            db, prof_scope, membership_id=membership.id, period_id=period.id, items=plan
        )

    scope = await identity_service.scope_for(db, student)
    version = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Implemented the loader and ran the baseline end to end.",
                "results": "The baseline reproduces the published score within one point.",
            }
        ],
    )
    return period, project, version


async def _baseline_items(db: AsyncSession, prof_scope: Scope, student_id: object, ids: object):
    baseline = await projects_service.effective_baseline_for_student(
        db,
        workspace_id=prof_scope.workspace_id,
        student_id=student_id,
        project_id=ids[0],
        period_id=ids[1],
    )
    assert baseline is not None
    return baseline.items


# ---------------------------------------------------------------- commitment completion


async def test_a_completed_plan_is_not_reported_as_zero(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The regression: every accepted fraction was hardcoded to Decimal(0)."""
    period, project, version = await _week(db, prof_scope, student_a)
    items = await _baseline_items(db, prof_scope, student_a.id, (project.id, period.id))

    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions={
                    "progress": DimensionRating(rating="3", rationale="done", evidence_ref_ids=[])
                },
                plan_items=[
                    PlanItemAssessment(
                        item_id=str(item.id),
                        proposed_completion=1.0,
                        reason="met",
                        evidence_ref_ids=[],
                    )
                    for item in items
                ],
            )
        }
    )

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=gateway,
    )

    assert assessment is not None
    assert assessment.plan_completion == Decimal("100.00")


async def test_completion_is_weighted_by_the_frozen_weights(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Three-weight item done, one-weight item untouched: 75%, not 50%."""
    period, project, version = await _week(db, prof_scope, student_a)
    items = await _baseline_items(db, prof_scope, student_a.id, (project.id, period.id))
    heavy = next(item for item in items if item.planned_outcome.startswith("Baseline"))

    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions={
                    "progress": DimensionRating(rating="3", rationale="done", evidence_ref_ids=[])
                },
                plan_items=[
                    PlanItemAssessment(
                        item_id=str(heavy.id),
                        proposed_completion=1.0,
                        reason="the log is in the report",
                        evidence_ref_ids=[],
                    )
                ],
            )
        }
    )

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=gateway,
    )

    assert assessment is not None
    # The item the draft said nothing about counts as zero, which is the floor its silence supports.
    assert assessment.plan_completion == Decimal("75.00")


async def test_without_a_baseline_completion_is_unavailable_rather_than_zero(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """metrics.py's stated rule: a missing baseline is not a score of nothing."""
    period, project, version = await _week(db, prof_scope, student_a, plan=None)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    assert assessment.plan_completion is None


async def test_the_rating_step_is_given_the_commitments_to_judge(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The prompt declared a <plan_baseline> section that nothing ever filled."""
    period, project, version = await _week(db, prof_scope, student_a)

    seen: list[dict] = []

    class _Capturing(FakeGateway):
        async def complete_structured(self, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs["prompt_id"] == "rate_rubric":
                seen.append(kwargs["inputs"])
            return await super().complete_structured(**kwargs)

    await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=_Capturing(),
    )

    assert seen, "the rating step ran"
    supplied = seen[0]["baseline"]
    assert [item["planned_outcome"] for item in supplied] == [
        "Baseline runs end to end",
        "Write the method section",
    ]
    assert all(item["item_id"] for item in supplied), "each one is addressable in the response"


# ---------------------------------------------------------------- coverage


async def test_a_dimension_the_model_omitted_counts_against_coverage(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """The regression: the denominator came from the response's own keys, so it was always full.

    The default rubric has four dimensions. Answering one of them well is not full coverage, and
    must not read as high confidence.
    """
    period, project, version = await _week(db, prof_scope, student_a, plan=None)

    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions={
                    "progress": DimensionRating(
                        rating="3", rationale="the loader runs", evidence_ref_ids=[]
                    )
                }
            )
        }
    )

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=gateway,
    )

    assert assessment is not None
    assert assessment.coverage_pct < Decimal("100.00")
    assert assessment.confidence is not Confidence.HIGH
    assert assessment.confidence_reasons, "and it says why"


async def test_rating_every_dimension_is_full_coverage(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, version = await _week(db, prof_scope, student_a, plan=None)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    assert assessment.coverage_pct == Decimal("100.00")
