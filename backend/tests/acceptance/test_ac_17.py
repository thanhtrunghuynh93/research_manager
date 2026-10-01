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
from app.identity import service as identity_service
from app.reporting import service as reporting_service
from tests.factories import make_entry, make_week, submit

pytestmark = pytest.mark.acceptance


async def test_ac_17_only_the_revised_entry_counts_as_changed(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await make_week(db, prof_scope, [student_a], projects=2)
    first = await submit(db, student_a, week)
    student_scope = await identity_service.scope_for(db, student_a)
    report = await reporting_service.get_report(db, student_scope, period_id=week.period.id)
    await reporting_service.request_revision(
        db,
        prof_scope,
        report_id=report.id,
        project_id=week.projects[0].id,
        reason="Name the baseline you compared against",
    )

    second = await submit(
        db,
        student_a,
        week,
        make_entry(week.projects[0].id, work="Implemented the loader; compared against CNN-B"),
        make_entry(week.projects[1].id),
    )

    changed = next(e for e in second.entries if e.project_id == week.projects[0].id)
    untouched = next(e for e in second.entries if e.project_id == week.projects[1].id)
    assert changed.content_changed_in_version_id == second.id
    assert untouched.content_changed_in_version_id == first.id
    assert second.version_no == 2, "history gains a version rather than replacing one"
