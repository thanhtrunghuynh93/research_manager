"""AC-08 — An approved holiday, project pause, or extension applies | The obligation and deadline
reflect the exception; no incorrect missing-report alert is generated.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.identity import models as identity_models
from app.notifications import service as notifications
from app.projects import service as projects_service
from app.reporting import models as reporting_models
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance


async def _overdue(db: AsyncSession, period_id: object) -> None:
    await db.execute(
        update(reporting_models.ReportingPeriod)
        .where(reporting_models.ReportingPeriod.id == period_id)
        .values(deadline_utc=now() - timedelta(minutes=1))
    )


async def test_ac_08_an_approved_leave_raises_no_alert(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)
    obligations = await reporting_service.list_obligations(db, prof_scope, week.period.id)
    await reporting_service.excuse_obligation(
        db, prof_scope, obligations[0].id, reason="Approved holiday"
    )
    await _overdue(db, week.period.id)

    assert await notifications.dispatch_missed_deadline(db, week.period.id) == []


async def test_ac_08_a_paused_project_owes_nothing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a, through=date(2026, 9, 27))
    await projects_service.update_project(db, prof_scope, week.projects[0].id, status="paused")

    periods = await reporting_service.list_periods(db, prof_scope)
    later = periods[1]
    assert await reporting_service.ensure_obligations(db, prof_scope, later.id) == []


async def test_ac_08_an_extension_moves_the_deadline_for_that_obligation_only(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)
    obligations = await reporting_service.list_obligations(db, prof_scope, week.period.id)
    await reporting_service.extend_obligation(
        db, prof_scope, obligations[0].id, until=now() + timedelta(days=2), reason="Cluster outage"
    )
    await _overdue(db, week.period.id)

    assert await notifications.dispatch_missed_deadline(db, week.period.id) == []
