"""UI-07: the notification records jobs raise, and who each one belongs to.

Use cases v0.3 retired reading notifications in the app, so there is no service read path left to
test. What survives is what the records are for: a job raises one, it belongs to exactly one
person, and the visibility policy still says so. These read through `repository` because that is
now the only reader besides the delivery path.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.notifications import repository, service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


async def _period_and_project(db: AsyncSession, prof_scope: Scope, student: identity_models.User):
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
    return period, project


async def test_submitting_a_report_notifies_the_professor(
    db: AsyncSession, prof: identity_models.User, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _period_and_project(db, prof_scope, student_a)
    scope = await identity_service.scope_for(db, student_a)

    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[{"project_id": project.id, "stage": "implementation", "work_performed": "Did it"}],
    )

    notifications = await repository.list_notifications(db, prof_scope)
    assert [n.kind for n in notifications] == [service.REPORT_SUBMITTED]
    assert notifications[0].recipient_id == prof.id


async def test_a_student_sees_only_their_own_notifications(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    await service.notify(
        db,
        workspace_id=prof_scope.workspace_id,
        recipient_id=student_a.id,
        kind=service.MISSED_DEADLINE,
        subject_table="weekly_reports",
        subject_id=student_a.id,
        payload={"reason": "Name the baseline"},
    )
    scope_b = await identity_service.scope_for(db, student_b)

    assert await repository.list_notifications(db, scope_b) == []
    scope_a = await identity_service.scope_for(db, student_a)
    assert len(await repository.list_notifications(db, scope_a)) == 1
