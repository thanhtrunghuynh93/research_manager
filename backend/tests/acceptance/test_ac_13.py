"""AC-13 — A report is late, an LLM call fails, or a source arrives after approval | Original
submission time is preserved; jobs can recover; approved history is not silently changed.

The model and approval halves arrive with the assessment module. What is provable now is the first
clause, which is the one the database enforces.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.identity import models as identity_models
from app.reporting import models as reporting_models
from app.reporting import service as reporting_service
from tests.acceptance.conftest import entry

pytestmark = pytest.mark.acceptance


async def test_ac_13_a_late_report_keeps_its_real_timestamp(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)
    await db.execute(
        update(reporting_models.ReportingPeriod)
        .where(reporting_models.ReportingPeriod.id == week.period.id)
        .values(deadline_utc=now() - timedelta(hours=2))
    )
    started = now()

    version = await reporting_service.submit_report(
        db, week.student_scope, period_id=week.period.id, entries=[entry(week.projects[0].id)]
    )

    assert version.timing_status is reporting_models.TimingStatus.LATE
    assert version.submitted_at >= started


async def test_ac_13_the_first_submission_time_cannot_be_moved(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)
    await reporting_service.submit_report(
        db, week.student_scope, period_id=week.period.id, entries=[entry(week.projects[0].id)]
    )
    report = await reporting_service.get_report(db, week.student_scope, period_id=week.period.id)

    with pytest.raises(DBAPIError, match="write-once"):
        await db.execute(
            update(reporting_models.WeeklyReport)
            .where(reporting_models.WeeklyReport.id == report.id)
            .values(first_submitted_at=now() + timedelta(days=1))
        )
    await db.rollback()


async def test_ac_13_a_submitted_version_cannot_be_rewritten(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)
    version = await reporting_service.submit_report(
        db, week.student_scope, period_id=week.period.id, entries=[entry(week.projects[0].id)]
    )

    with pytest.raises(DBAPIError, match="immutable"):
        await db.execute(
            update(reporting_models.ProjectReportEntry)
            .where(reporting_models.ProjectReportEntry.report_version_id == version.id)
            .values(work_performed="something else entirely")
        )
    await db.rollback()
