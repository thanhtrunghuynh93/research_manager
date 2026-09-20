"""ASSESS-01/07/09: the snapshot, the pipeline over it, and what a draft is allowed to claim.

The pipeline's job is to prepare a draft the professor can trust enough to argue with: it must show
what it looked at, refuse to cite what it did not, and say plainly when it could not tell.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.ai.schemas import DimensionRating, RubricOutput
from app.assessment import models, service
from app.assessment.metrics import Confidence
from app.core.authz import Scope
from app.core.types import Visibility
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _week(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
) -> tuple[object, object]:
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
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


def _entry(
    project_id: object, work: str = "Implemented the data loader and ran the baseline."
) -> dict:
    return {
        "project_id": project_id,
        "stage": "implementation",
        "work_performed": work,
        "results": "The baseline reproduces the published score within one point.",
        "next_plan": {"items": [{"planned_outcome": "Run the ablation", "weight": 1}]},
    }


async def _submit(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User, **kwargs
) -> tuple[object, object, object]:
    period, project = await _week(db, prof_scope, student)
    scope = await identity_service.scope_for(db, student)
    version = await reporting_service.submit_report(
        db, scope, period_id=period.id, entries=[_entry(project.id, **kwargs)]
    )
    return period, project, version


async def test_a_snapshot_records_what_was_considered(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-01: a recorded evidence snapshot, with the window it covered.
    period, project, version = await _submit(db, prof_scope, student_a)

    snapshot = await service.build_snapshot(
        db, student_id=student_a.id, project_id=project.id, period_id=period.id
    )

    assert snapshot.item_count >= 1, "the report entry itself is evidence"
    assert snapshot.window_start_utc < snapshot.window_end_utc
    assert snapshot.access_epoch >= 1


async def test_a_snapshot_excludes_professor_only_material(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-01/QA-06: the approved assessment is published to the student, so its evidence must
    # be evidence the student may see.
    period, project, _ = await _submit(db, prof_scope, student_a)
    await service.add_supervision_note(
        db,
        prof_scope,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        body="Private: this student is struggling and I should raise it gently.",
    )

    snapshot = await service.build_snapshot(
        db, student_id=student_a.id, project_id=project.id, period_id=period.id
    )
    items = await service.snapshot_items(db, snapshot.id)

    texts = " ".join(item.text for item in items)
    assert "struggling" not in texts
    assert all(item.visibility is not Visibility.PROFESSOR_ONLY for item in items)


async def test_a_draft_is_produced_for_review_rather_than_published(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-08: generated assessments begin as drafts, visible to the professor.
    period, project, version = await _submit(db, prof_scope, student_a)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    assert assessment.version_no == 1
    review = await service.current_review(db, prof_scope, assessment.id)
    assert review is not None and review.state is models.ReviewState.DRAFT

    student_scope = await identity_service.scope_for(db, student_a)
    assert await service.list_assessments(db, student_scope, student_id=student_a.id) == []


async def test_the_index_is_computed_from_the_ratings(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ADR 0006: the arithmetic is ours, not the model's.
    period, project, version = await _submit(db, prof_scope, student_a)
    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions=[
                    DimensionRating(
                        dimension_id="progress", rating="3", rationale="met", evidence_ref_ids=[]
                    ),
                    DimensionRating(
                        dimension_id="learning", rating="4", rationale="beyond", evidence_ref_ids=[]
                    ),
                    DimensionRating(
                        dimension_id="rigor", rating="3", rationale="met", evidence_ref_ids=[]
                    ),
                    DimensionRating(
                        dimension_id="artifacts",
                        rating="2",
                        rationale="partial",
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
    assert assessment.progress_index == 79, "the specification's worked example, end to end"


async def test_an_unknown_dimension_withholds_the_index(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-04: otherwise show "Not rated — insufficient evidence" and the assessable dimensions.
    period, project, version = await _submit(db, prof_scope, student_a)
    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions=[
                    DimensionRating(
                        dimension_id="progress", rating="3", rationale="met", evidence_ref_ids=[]
                    ),
                    DimensionRating(
                        dimension_id="learning",
                        rating="unknown",
                        rationale="nothing settles this",
                        evidence_ref_ids=[],
                    ),
                    DimensionRating(
                        dimension_id="rigor", rating="3", rationale="met", evidence_ref_ids=[]
                    ),
                    DimensionRating(
                        dimension_id="artifacts",
                        rating="2",
                        rationale="partial",
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
    assert assessment.progress_index is None
    assert assessment.ratings["progress"]["rating"] == 3, "the rateable dimensions are still shown"


async def test_a_fabricated_citation_is_dropped_and_the_rating_downgraded(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-07/AC-12: a citation that is not in the snapshot cannot survive into an assessment.
    period, project, version = await _submit(db, prof_scope, student_a)
    gateway = FakeGateway(
        responses={
            "rate_rubric": RubricOutput(
                dimensions=[
                    DimensionRating(
                        dimension_id="progress",
                        rating="4",
                        rationale="cites something that does not exist",
                        evidence_ref_ids=["11111111-1111-1111-1111-111111111111"],
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
    assert progress["rating"] == "unknown"
    assert progress["evidence_ref_ids"] == []
    assert any("not in the snapshot" in reason for reason in progress["validation_notes"])


async def test_a_model_failure_leaves_the_run_partial_and_the_report_untouched(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-13: jobs can recover; the report keeps its original submission time.
    period, project, version = await _submit(db, prof_scope, student_a)
    gateway = FakeGateway(fail_prompts={"rate_rubric"})

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=gateway,
    )

    assert assessment is None
    run = await service.latest_run(
        db, student_id=student_a.id, project_id=project.id, period_id=period.id
    )
    assert run is not None and run.state is models.RunState.PARTIAL
    assert run.error_summary and "rate_rubric" in run.error_summary


async def test_a_restricted_project_is_never_sent_to_a_provider(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Architecture §10: the pipeline still builds the snapshot and the metrics; nobody is called.
    period, project, version = await _submit(db, prof_scope, student_a)
    await projects_service.update_project(db, prof_scope, project.id, ai_restricted=True)
    gateway = FakeGateway()

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=gateway,
    )

    assert gateway.calls == [], "no prompt reached the gateway"
    assert assessment is not None
    assert assessment.progress_index is None
    assert assessment.reason == "restricted"


async def test_the_assessment_records_how_it_was_produced(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-09: rubric version, model, prompt versions, snapshot, and report version.
    period, project, version = await _submit(db, prof_scope, student_a)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    assert assessment.rubric_version_id is not None
    assert assessment.snapshot_id is not None
    assert assessment.report_version_id == version.id
    assert assessment.model_name == "fake-1"
    assert "rate_rubric" in assessment.prompt_versions


async def test_reported_activity_alone_does_not_raise_a_rating(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-14: repetitive commits or verbose text do not increase research-progress ratings.
    period, project, version = await _submit(db, prof_scope, student_a, work="Did work. " * 200)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    ratings = {name: rating["rating"] for name, rating in assessment.ratings.items()}
    assert all(value in (3, "unknown") for value in ratings.values()), (
        "length is not achievement: the default rating does not move with it"
    )


async def test_confidence_is_recorded_with_its_reasons(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, version = await _submit(db, prof_scope, student_a)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    assert assessment.confidence in {level.value for level in Confidence}
    # No baseline was frozen for this week, so that must be among the stated reasons.
    assert any("baseline" in reason for reason in assessment.confidence_reasons)
