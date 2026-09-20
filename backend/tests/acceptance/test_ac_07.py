"""AC-07 — A report claims a result for which accessible evidence is incomplete | The assessment
labels the claim and uncertainty; the assistant does not present it as independently verified.

The assistant half arrives with that module. What is provable now is that the assessment refuses to
carry a claim it could not check, and says so.
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


async def _submitted(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
) -> tuple[object, object, object]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    scope = await identity_service.scope_for(db, student)
    version = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Ran the full sweep on the private cluster.",
                "results": "We beat the published state of the art by four points.",
                "next_plan": {},
            }
        ],
    )
    return period, project, version


async def test_ac_07_a_claim_cited_to_nothing_cannot_stand(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, version = await _submitted(db, prof_scope, student_a)
    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions=[
                    DimensionRating(
                        dimension_id="progress",
                        rating="4",
                        rationale="state of the art, as reported",
                        evidence_ref_ids=["99999999-9999-9999-9999-999999999999"],
                    )
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
    progress = assessment.ratings["progress"]
    assert progress["rating"] == "unknown", "a rating whose support is invented is not a rating"
    assert progress["evidence_ref_ids"] == []
    assert assessment.progress_index is None
    assert any("not in the snapshot" in note for note in progress["validation_notes"])


async def test_ac_07_an_unverifiable_claim_lowers_confidence_and_is_named(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # The fake gateway marks claims unverifiable once the snapshot's evidence runs out, which is
    # the honest answer when a private cluster result cannot be inspected (REPO-08).
    period, project, version = await _submitted(db, prof_scope, student_a)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    discrepancies = assessment.narrative.get("discrepancies", [])
    assert any(item["status"] == "unverifiable" for item in discrepancies)
    assert assessment.confidence in ("medium", "low")
