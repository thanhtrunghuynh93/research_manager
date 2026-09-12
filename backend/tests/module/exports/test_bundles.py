"""Exports (UI-06, requirements §11 "Portability").

Two requirements pull in opposite directions and both have to hold. An export must be complete
enough to be portable — identifiers, versions, relationships, approval status, so the records can
be reconstructed elsewhere. And it must carry exactly the authority of the person downloading it:
"export authorization must match interactive access" means a student's download is their own
records and nothing else, including nothing about the classmates they share a project with.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.core.errors import ForbiddenError
from app.exports import service as exports
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _workspace_with_two_students(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
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
    for student in (student_a, student_b):
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
        )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)

    for student, result in ((student_a, "nDCG@10 is 0.412"), (student_b, "recall@100 is 0.71")):
        scope = await identity_service.scope_for(db, student)
        await reporting_service.submit_report(
            db,
            scope,
            period_id=period.id,
            entries=[
                {
                    "project_id": project.id,
                    "stage": "implementation",
                    "work_performed": f"{student.display_name} ran the baseline.",
                    "results": result,
                }
            ],
        )
    return period, project


async def test_the_bundle_says_who_asked_for_it_and_when(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """Portability: an export nobody can date or attribute is not a record of anything."""
    await _workspace_with_two_students(db, prof_scope, student_a, student_b)

    bundle = await exports.build(db, prof_scope)

    assert bundle.metadata["generated_for"] == str(prof_scope.user_id)
    assert bundle.metadata["role"] == "prof"
    assert bundle.metadata["generated_at"]
    assert bundle.metadata["schema_version"]


async def test_a_report_export_carries_its_version_timing_and_entries(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    await _workspace_with_two_students(db, prof_scope, student_a, student_b)

    bundle = await exports.build(db, prof_scope, kinds=["reports"])

    reports = bundle.records["reports"]
    assert len(reports) == 2
    first = reports[0]
    assert first["version_no"] == 1
    assert first["timing_status"]
    assert first["submitted_at"]
    assert first["entries"][0]["results"]


async def test_a_student_exports_their_own_records_and_no_one_elses(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """AC-02/UI-06: the download is not a second permission model."""
    await _workspace_with_two_students(db, prof_scope, student_a, student_b)
    scope = await identity_service.scope_for(db, student_a)

    bundle = await exports.build(db, scope, kinds=["reports"])

    owners = {row["student_id"] for row in bundle.records["reports"]}
    assert owners == {str(student_a.id)}
    assert all("recall@100" not in str(row) for row in bundle.records["reports"])


async def test_a_student_export_carries_only_approved_assessments(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """ASSESS-08: a draft is not published, and an export is a publication."""
    period, project = await _workspace_with_two_students(db, prof_scope, student_a, student_b)
    await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=FakeGateway(),
    )
    scope = await identity_service.scope_for(db, student_a)

    bundle = await exports.build(db, scope, kinds=["assessments"])

    assert bundle.records["assessments"] == []


async def test_an_assessment_export_states_its_approval_status(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    period, project = await _workspace_with_two_students(db, prof_scope, student_a, student_b)
    assessment = await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=FakeGateway(),
    )
    assert assessment is not None

    bundle = await exports.build(db, prof_scope, kinds=["assessments"])

    row = bundle.records["assessments"][0]
    assert row["review_state"] == "draft"
    assert row["published_at"] is None
    assert row["rubric_version_id"]
    assert "coverage_pct" in row


async def test_supervision_notes_are_never_in_a_students_bundle(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """QA-06: a note the student may not read is not made readable by asking for a file."""
    _period, project = await _workspace_with_two_students(db, prof_scope, student_a, student_b)
    await assessment_service.add_supervision_note(
        db,
        prof_scope,
        body="Discuss the pace privately.",
        student_id=student_a.id,
        project_id=project.id,
    )
    scope = await identity_service.scope_for(db, student_a)

    # Everything a student is allowed to ask for, which is the whole of their bundle.
    allowed = [kind for kind in exports.KINDS if kind not in exports.PROFESSOR_ONLY]
    bundle = await exports.build(db, scope, kinds=allowed)

    assert "supervision_notes" not in bundle.records
    assert "Discuss the pace privately" not in str(bundle.records)


async def test_a_student_asking_for_supervision_notes_is_refused_rather_than_given_an_empty_list(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """An empty list would read as "there are none", which is a different claim."""
    scope = await identity_service.scope_for(db, student_a)

    with pytest.raises(ForbiddenError):
        await exports.build(db, scope, kinds=["supervision_notes"])


async def test_an_unknown_kind_is_refused_rather_than_silently_dropped(
    db: AsyncSession, prof_scope: Scope
) -> None:
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        await exports.build(db, prof_scope, kinds=["everything"])


async def test_the_csv_rendering_has_one_row_per_assessment_and_a_header(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """UI-06: a printable, spreadsheet-readable form beside the machine-readable one."""
    period, project = await _workspace_with_two_students(db, prof_scope, student_a, student_b)
    await assessment_service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=FakeGateway(),
    )

    bundle = await exports.build(db, prof_scope, kinds=["assessments"])
    text = exports.to_csv(bundle, "assessments")

    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[0].startswith("assessment_id,")
    assert len(lines) == 2


async def test_filters_narrow_the_bundle_without_widening_what_may_be_seen(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    await _workspace_with_two_students(db, prof_scope, student_a, student_b)

    bundle = await exports.build(db, prof_scope, kinds=["reports"], student_id=student_b.id)

    assert {row["student_id"] for row in bundle.records["reports"]} == {str(student_b.id)}
    assert bundle.metadata["filters"]["student_id"] == str(student_b.id)
