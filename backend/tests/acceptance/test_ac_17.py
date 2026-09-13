"""AC-17 — A student resubmits a package after a revision request on one of two project entries |
The unchanged entry keeps its existing assessment; only the changed entry produces a new draft
assessment.

The assessment is created from `content_changed_in_version_id`, so what this proves is the fact the
assessment pipeline will read: the unchanged entry still points at the version it last changed in.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.reporting import service as reporting_service
from tests.acceptance.conftest import entry

pytestmark = pytest.mark.acceptance


async def test_ac_17_only_the_revised_entry_counts_as_changed(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a, project_count=2)
    first = await reporting_service.submit_report(
        db,
        week.student_scope,
        period_id=week.period.id,
        entries=[entry(week.projects[0].id), entry(week.projects[1].id)],
    )
    report = await reporting_service.get_report(db, week.student_scope, period_id=week.period.id)
    await reporting_service.request_revision(
        db,
        prof_scope,
        report_id=report.id,
        project_id=week.projects[0].id,
        reason="Name the baseline you compared against",
    )

    second = await reporting_service.submit_report(
        db,
        week.student_scope,
        period_id=week.period.id,
        entries=[
            entry(week.projects[0].id, work="Implemented the loader; compared against CNN-B"),
            entry(week.projects[1].id),
        ],
    )

    changed = next(e for e in second.entries if e.project_id == week.projects[0].id)
    untouched = next(e for e in second.entries if e.project_id == week.projects[1].id)
    assert changed.content_changed_in_version_id == second.id
    assert untouched.content_changed_in_version_id == first.id
    assert second.version_no == 2, "history gains a version rather than replacing one"
