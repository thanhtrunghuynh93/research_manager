"""AC-02 — A student on one project requests another student's private report or its citation URL |
Access is denied in API, UI, search, cached responses, downloads, and exports.

Search, downloads, and exports arrive with later modules; each one compiles the same predicate, so
what is proved here is that the predicate denies the read through both the service and HTTP.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.errors import NotFoundError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.reporting import models as reporting_models
from app.reporting import service as reporting_service
from tests.acceptance.conftest import entry
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.acceptance


async def test_ac_02_another_students_report_is_not_readable(
    db: AsyncSession,
    client: AsyncClient,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    week_for,
) -> None:
    week = await week_for(db, prof_scope, student_a)
    await reporting_service.submit_report(
        db, week.student_scope, period_id=week.period.id, entries=[entry(week.projects[0].id)]
    )
    other = await identity_service.scope_for(db, student_b)

    # Through the service.
    with pytest.raises(NotFoundError):
        await reporting_service.get_report(
            db, other, period_id=week.period.id, student_id=student_a.id
        )

    # Through the predicate any query would compile.
    rows = (
        (
            await db.execute(
                select(reporting_models.WeeklyReport.id).where(
                    visible_to(other, reporting_models.WeeklyReport)
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []

    # Through HTTP.
    await client.post(
        "/api/v1/auth/login", json={"email": student_b.email, "password": DEFAULT_PASSWORD}
    )
    response = await client.get(
        f"/api/v1/periods/{week.period.id}/report", params={"student_id": str(student_a.id)}
    )
    assert response.status_code == 404, "absent, not forbidden: a 403 would confirm it exists"
