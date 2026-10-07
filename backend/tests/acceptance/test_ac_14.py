"""AC-14 — A student submits repetitive attachments or verbose text without new substantive
evidence | Volume or length alone does not increase research-progress ratings.

Restated in requirements 0.11: the commits this used to count came from the repository connector,
which is gone (ADR 0022). Attachments are the evidence a student can still pile up.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service
from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import service as evidence_service
from app.evidence.models import EvidenceSourceKind
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance

WEEK = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)


async def _assess(
    db: AsyncSession,
    prof_scope: Scope,
    student: identity_models.User,
    *,
    work: str,
    attachment_count: int,
) -> object:
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

    # The same notes attached over and over: volume, and nothing new in it.
    for _ in range(attachment_count):
        await evidence_service.index_evidence(
            db,
            workspace_id=prof_scope.workspace_id,
            project_id=project.id,
            owner_student_id=student.id,
            visibility=Visibility.STUDENT_PRIVATE,
            source_kind=EvidenceSourceKind.ARTIFACT_VERSION,
            source_id=uuid4(),
            source_version="1",
            locator="attachment",
            text="Loader notes, work in progress. " * 40,
            source_time=WEEK,
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
                "work_performed": work,
                "results": "Work continues.",
                "next_plan": {},
            }
        ],
    )
    return await service.run_pipeline(
        db,
        student_id=student.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )


async def test_ac_14_length_and_attachment_volume_do_not_move_the_rating(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    modest = await _assess(
        db,
        prof_scope,
        student_a,
        work="Fixed the loader's off-by-one on the last split.",
        attachment_count=0,
    )
    voluminous = await _assess(
        db,
        prof_scope,
        student_b,
        work="Worked hard on the loader. " * 150,
        attachment_count=40,
    )

    assert modest is not None and voluminous is not None
    assert voluminous.progress_index == modest.progress_index, (
        "forty attachments and a thousand words did not buy a higher rating"
    )
