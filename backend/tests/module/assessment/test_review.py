"""ASSESS-08/09/10 and AC-03: review, override, correction, and what a new version means."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import models, service
from app.core.authz import Scope
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _assessed(
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
                "work_performed": "Implemented the loader and reproduced the baseline.",
                "results": "Within one point of the published score.",
                "next_plan": {},
            }
        ],
    )
    assessment = await service.run_pipeline(
        db,
        student_id=student.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )
    return period, project, assessment


async def test_approval_publishes_the_assessment_to_the_student(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-08: approval publishes; a draft is not visible to the student.
    _, _, assessment = await _assessed(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)
    assert await service.list_assessments(db, scope, student_id=student_a.id) == []

    await service.approve(db, prof_scope, assessment.id)

    published = await service.list_assessments(db, scope, student_id=student_a.id)
    assert [item.id for item in published] == [assessment.id]


async def test_a_student_cannot_approve_their_own_assessment(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    _, _, assessment = await _assessed(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ForbiddenError):
        await service.approve(db, scope, assessment.id)


async def test_an_override_keeps_the_original_model_output(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-08: preserve original model output, approved output, actor, timestamp, and history.
    _, _, assessment = await _assessed(db, prof_scope, student_a)
    original = dict(assessment.ratings)

    review = await service.approve(
        db,
        prof_scope,
        assessment.id,
        override={"ratings": {"progress": {"rating": 4}}},
        rationale="The write-up understates a result I saw in the meeting.",
    )

    assert review.override == {"ratings": {"progress": {"rating": 4}}}
    assert review.rationale.startswith("The write-up")
    stored = await service.get_assessment(db, prof_scope, assessment.id)
    assert stored.ratings == original, "the model's own output is untouched"
    assert stored.effective_ratings["progress"]["rating"] == 4, "the override is what stands"


async def test_an_override_without_a_reason_is_refused(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-08: the professor can adjust a rating "with a recorded reason".
    _, _, assessment = await _assessed(db, prof_scope, student_a)

    with pytest.raises(ValidationError):
        await service.approve(
            db, prof_scope, assessment.id, override={"ratings": {"progress": {"rating": 4}}}
        )


async def test_an_assessment_version_cannot_be_edited(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-09: new inputs create new versions and never silently rewrite approved history.
    _, _, assessment = await _assessed(db, prof_scope, student_a)

    with pytest.raises(DBAPIError, match="immutable"):
        await db.execute(
            update(models.AssessmentVersion)
            .where(models.AssessmentVersion.id == assessment.id)
            .values(progress_index=100)
        )
    await db.rollback()


async def test_a_revised_report_creates_a_new_version_and_leaves_the_approved_one_standing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-03: original report and assessment remain intact; a new assessment awaits review.
    period, project, first = await _assessed(db, prof_scope, student_a)
    await service.approve(db, prof_scope, first.id)
    scope = await identity_service.scope_for(db, student_a)

    revised = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Implemented the loader, reproduced it, added the ablation.",
                "results": "Within one point, and the ablation isolates the gain.",
                "next_plan": {},
            }
        ],
    )
    second = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=revised.id,
        gateway=FakeGateway(),
    )

    assert second is not None and second.version_no == 2
    assert second.id != first.id
    new_review = await service.current_review(db, prof_scope, second.id)
    assert new_review is not None and new_review.state is models.ReviewState.DRAFT

    original = await service.get_assessment(db, prof_scope, first.id)
    assert original.progress_index == first.progress_index, "the approved history is untouched"
    published = await service.list_assessments(db, scope, student_id=student_a.id)
    assert [item.id for item in published] == [first.id], "the student still sees the approved one"


async def test_an_unchanged_entry_produces_no_new_assessment(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-17/ASSESS-09: a new report version only re-assesses the entries whose content changed.
    period, project, first = await _assessed(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    resubmitted = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Implemented the loader and reproduced the baseline.",
                "results": "Within one point of the published score.",
                "next_plan": {},
            }
        ],
    )
    again = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=resubmitted.id,
        gateway=FakeGateway(),
    )

    assert again is None, "nothing changed in this entry, so nothing is re-assessed"
    versions = await service.list_versions(
        db, prof_scope, student_id=student_a.id, project_id=project.id, period_id=period.id
    )
    assert len(versions) == 1


async def test_a_student_can_request_a_correction_with_evidence(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # ASSESS-08: students can request corrections and add evidence.
    _, _, assessment = await _assessed(db, prof_scope, student_a)
    await service.approve(db, prof_scope, assessment.id)
    scope = await identity_service.scope_for(db, student_a)

    request = await service.request_correction(
        db,
        scope,
        assessment.id,
        body="The ablation log shows the second result; it was attached to the entry.",
    )

    assert request.kind is models.FeedbackKind.CORRECTION_REQUEST
    visible = await service.list_feedback(db, prof_scope, assessment.id)
    assert [item.id for item in visible] == [request.id]


async def test_a_student_cannot_request_a_correction_on_someone_elses_assessment(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    _, _, assessment = await _assessed(db, prof_scope, student_a)
    await service.approve(db, prof_scope, assessment.id)
    scope = await identity_service.scope_for(db, student_b)

    with pytest.raises(NotFoundError):
        await service.request_correction(db, scope, assessment.id, body="not mine")


async def test_a_trend_labels_a_rubric_change_rather_than_comparing_across_it(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-10: incompatible scores are not presented as directly comparable.
    _, project, assessment = await _assessed(db, prof_scope, student_a)
    await service.approve(db, prof_scope, assessment.id)

    series = await service.progress_series(
        db, prof_scope, student_id=student_a.id, project_id=project.id
    )

    assert len(series) == 1
    assert series[0].rubric_version_id == assessment.rubric_version_id
    assert series[0].progress_index == assessment.progress_index


# ---------------------------------------------------------------- what may still be approved
#
# A draft in an open tab outlives the thing it describes. Approval guarded only "already
# approved", so a superseded or withdrawn review could be published from one.


async def test_a_superseded_assessment_cannot_be_approved(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Both versions would then be published, and both would appear in the student's trend."""
    period, project, first = await _assessed(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    revised = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Implemented the loader, reproduced it, added the ablation.",
                "results": "Within one point, and the ablation isolates the gain.",
            }
        ],
    )
    second = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=revised.id,
        gateway=FakeGateway(),
    )
    assert second is not None

    stale = await service.current_review(db, prof_scope, first.id)
    assert stale is not None and stale.state is models.ReviewState.SUPERSEDED

    with pytest.raises(ConflictError, match="newer assessment"):
        await service.approve(db, prof_scope, first.id)


async def test_a_withdrawn_assessment_is_not_re_approved(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, assessment = await _assessed(db, prof_scope, student_a)
    await service.approve(db, prof_scope, assessment.id)
    await service.withdraw(db, prof_scope, assessment.id)

    with pytest.raises(ConflictError, match="withdrawn"):
        await service.approve(db, prof_scope, assessment.id)


async def test_withdrawing_clears_the_publication_time(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """It is not published any more, so it does not have a time at which it is published."""
    _period, _project, assessment = await _assessed(db, prof_scope, student_a)
    await service.approve(db, prof_scope, assessment.id)

    await service.withdraw(db, prof_scope, assessment.id)

    withdrawn = await service.get_assessment(db, prof_scope, assessment.id)
    assert withdrawn.published_at is None
