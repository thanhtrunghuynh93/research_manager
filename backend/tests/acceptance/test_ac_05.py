"""AC-05 — A student documents a rigorous negative result or a useful theoretical result without
commits | The rubric can credit learning, rigor, and relevant artifacts without requiring
repository activity.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import DimensionRating, RubricOutput
from app.assessment import service
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance


async def test_ac_05_a_negative_result_without_code_can_be_rated_fully(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Estimator theory", stage="theory"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    scope = await identity_service.scope_for(db, student_a)

    version = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "theory",
                "work_performed": (
                    "Tested the hypothesis that the estimator is unbiased under the weaker"
                    " assumption. Constructed a counterexample and checked it by hand."
                ),
                "results": (
                    "The hypothesis is false: the counterexample shows a bias of order 1/n."
                    " This closes the direction we agreed to test."
                ),
                "next_plan": {},
            }
        ],
    )

    # There is no repository on this project at all, and no commit anywhere.
    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions=[
                    DimensionRating(
                        dimension_id="progress",
                        rating="3",
                        rationale="the agreed test was carried out",
                        evidence_ref_ids=[],
                    ),
                    DimensionRating(
                        dimension_id="learning",
                        rating="4",
                        rationale="a rigorous negative result closes a direction",
                        evidence_ref_ids=[],
                    ),
                    DimensionRating(
                        dimension_id="rigor",
                        rating="4",
                        rationale="the counterexample is checkable",
                        evidence_ref_ids=[],
                    ),
                    DimensionRating(
                        dimension_id="artifacts",
                        rating="3",
                        rationale="the proof is written up",
                        evidence_ref_ids=[],
                    ),
                ]
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
    assert assessment.progress_index == 89, "a negative result is creditable work"
    assert all(rating["rating"] != "unknown" for rating in assessment.ratings.values()), (
        "no dimension was withheld for want of commits"
    )
    # The absence of a repository is not a gap in coverage.
    assert all("repository" not in reason for reason in assessment.confidence_reasons)
