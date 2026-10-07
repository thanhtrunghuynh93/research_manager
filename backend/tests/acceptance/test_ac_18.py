"""AC-18 — A student joins a project mid-period, or the previous report was missing, so no frozen
plan exists | The report is still accepted, and its next-week plan is what the following week
freezes; commitment completion is unavailable for this week; the progress rubric can still be
applied to the available evidence.

Restated in requirements 0.10: the professor no longer accepts a first plan mid-week. That flow had
no route and no screen, so the week with nothing frozen simply has nothing to measure against.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.projects import models as projects_models
from app.projects import service as projects_service
from app.reporting import service as reporting_service
from tests.factories import make_week, submit

pytestmark = pytest.mark.acceptance


async def test_ac_18_with_nothing_frozen_completion_is_unavailable_and_the_report_is_accepted(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await make_week(db, prof_scope, [student_a])

    # Nothing to freeze: this is the student's first week on the project.
    baselines = await reporting_service.freeze_baselines(db, prof_scope, week.period.id)
    assert [b.state for b in baselines] == [projects_models.BaselineState.EMPTY]

    membership_id = baselines[0].membership_id
    assert (
        await projects_service.effective_baseline(
            db, prof_scope, membership_id=membership_id, period_id=week.period.id
        )
        is None
    ), "commitment completion is unavailable"

    # The report is still accepted.
    version = await submit(db, student_a, week)
    assert version.version_no == 1
