"""AC-03 — A submitted report is revised after the professor has approved an assessment | Original
report and assessment remain intact; a new assessment references the new version and awaits review.

Two records the student can see are at stake, and neither may move under them. The approved
assessment is what they were told about their week; the report version is what they actually wrote.
A revision adds to both histories rather than editing either, and the new draft waits for a person
exactly as the first one did.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service as assessment_service
from app.assessment.schemas import ReviewState
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance


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
        db, prof_scope, title="Retrieval baselines", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


async def _submit(
    db: AsyncSession,
    student: identity_models.User,
    period: object,
    project: object,
    *,
    results: str,
) -> object:
    scope = await identity_service.scope_for(db, student)
    return await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,  # type: ignore[attr-defined]
        entries=[
            {
                "project_id": project.id,  # type: ignore[attr-defined]
                "stage": "implementation",
                "work_performed": "Ran the baseline.",
                "results": results,
            }
        ],
    )


async def _approved_assessment(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
) -> tuple[object, object, object, object]:
    period, project = await _week(db, prof_scope, student)
    first_version = await _submit(
        db, student, period, project, results="nDCG@10 is 0.412 on the internal split."
    )
    assessment = await assessment_service.run_pipeline(
        db,
        student_id=student.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=first_version.id,  # type: ignore[attr-defined]
        gateway=FakeGateway(),
    )
    assert assessment is not None
    await assessment_service.approve(db, prof_scope, assessment.id)
    return period, project, first_version, assessment


async def test_ac_03_the_approved_assessment_stays_published_when_the_report_is_revised(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, _first, approved = await _approved_assessment(db, prof_scope, student_a)

    second_version = await _submit(
        db, student_a, period, project, results="Corrected: nDCG@10 is 0.408, not 0.412."
    )
    await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=second_version.id,
        gateway=FakeGateway(),
    )

    still_there = await assessment_service.get_assessment(db, prof_scope, approved.id)
    assert still_there.version_no == approved.version_no
    assert still_there.progress_index == approved.progress_index
    assert still_there.ratings == approved.ratings


async def test_ac_03_the_new_assessment_references_the_new_version_and_awaits_review(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, _first, approved = await _approved_assessment(db, prof_scope, student_a)

    second_version = await _submit(
        db, student_a, period, project, results="Corrected: nDCG@10 is 0.408, not 0.412."
    )
    revised = await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=second_version.id,
        gateway=FakeGateway(),
    )

    assert revised is not None
    assert revised.version_no == approved.version_no + 1
    assert revised.report_version_id == second_version.id
    review = await assessment_service.current_review(db, prof_scope, revised.id)
    assert review is not None and review.state is ReviewState.DRAFT


async def test_ac_03_the_student_sees_the_approved_version_until_the_new_one_is_approved(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """ASSESS-08: approval is the publication step, and a draft is not a publication."""
    period, project, _first, approved = await _approved_assessment(db, prof_scope, student_a)
    second_version = await _submit(
        db, student_a, period, project, results="Corrected: nDCG@10 is 0.408, not 0.412."
    )
    await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=second_version.id,
        gateway=FakeGateway(),
    )
    student_scope = await identity_service.scope_for(db, student_a)

    visible = await assessment_service.list_assessments(
        db, student_scope, student_id=student_a.id, project_id=project.id
    )

    assert [row.id for row in visible] == [approved.id]


async def test_ac_03_the_original_report_version_cannot_be_edited(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """REP-05: a submission creates an immutable version, enforced by the database (§5.3)."""
    from sqlalchemy import update

    from app.reporting.models import ReportVersion

    _period, _project, first_version, _approved = await _approved_assessment(
        db, prof_scope, student_a
    )

    with pytest.raises(DBAPIError):
        await db.execute(
            update(ReportVersion)
            .where(ReportVersion.id == first_version.id)
            .values(idempotency_key="rewritten")
        )
    await db.rollback()


async def test_ac_03_both_report_versions_remain_readable(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project, first_version, _approved = await _approved_assessment(
        db, prof_scope, student_a
    )
    second_version = await _submit(
        db, student_a, period, project, results="Corrected: nDCG@10 is 0.408, not 0.412."
    )

    original = await reporting_service.get_version(db, prof_scope, first_version.id)
    revised = await reporting_service.get_version(db, prof_scope, second_version.id)

    assert original.entries[0].results.startswith("nDCG@10 is 0.412")
    assert revised.entries[0].results.startswith("Corrected")
    assert original.submitted_at <= revised.submitted_at
