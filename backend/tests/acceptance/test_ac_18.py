"""AC-18 — A student joins a project mid-period, or the previous report was missing, so no frozen
plan exists | The report accepts a first plan; commitment completion is unavailable until the
professor accepts the baseline; the progress rubric can still be applied to the available evidence.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.projects import models as projects_models
from app.projects import service as projects_service
from app.reporting import service as reporting_service
from tests.acceptance.conftest import entry

pytestmark = pytest.mark.acceptance


async def test_ac_18_a_first_plan_becomes_a_commitment_only_once_accepted(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)

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

    # The report is still accepted, and carries the plan the student proposes.
    version = await reporting_service.submit_report(
        db, week.student_scope, period_id=week.period.id, entries=[entry(week.projects[0].id)]
    )
    assert version.version_no == 1

    proposed = await projects_service.propose_baseline(
        db,
        week.student_scope,
        membership_id=membership_id,
        period_id=week.period.id,
        items=[{"planned_outcome": "Run the baseline end to end", "weight": 1}],
    )
    assert proposed.state is projects_models.BaselineState.PROPOSED
    assert (
        await projects_service.effective_baseline(
            db, prof_scope, membership_id=membership_id, period_id=week.period.id
        )
        is None
    ), "still unavailable while the plan is only proposed"

    accepted = await projects_service.accept_baseline(db, prof_scope, proposed.id)

    effective = await projects_service.effective_baseline(
        db, prof_scope, membership_id=membership_id, period_id=week.period.id
    )
    assert effective is not None and effective.id == accepted.id
    assert accepted.approved_at is not None
