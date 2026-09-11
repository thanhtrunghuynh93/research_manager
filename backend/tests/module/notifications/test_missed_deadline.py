"""REP-08: the automatic missed-deadline email, evaluated at send time.

The job runs at 00:00 local on the meeting day. What matters is that it reads the obligations when
it sends rather than when it was scheduled, sends at most one email per student per period, and
says nothing about anyone else's work.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ValidationError
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.notifications import models, service
from app.projects import service as projects_service
from app.reporting import models as reporting_models
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


class Week:
    def __init__(self, period: object, projects: list[object]) -> None:
        self.period = period
        self.projects = projects


async def _week(
    db: AsyncSession,
    prof_scope: Scope,
    students: list[identity_models.User],
    *,
    project_count: int = 1,
) -> Week:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    projects = []
    for index in range(project_count):
        project = await projects_service.create_project(
            db, prof_scope, title=f"Project {index}", stage="implementation"
        )
        await projects_service.update_project(db, prof_scope, project.id, status="active")
        for student in students:
            await projects_service.add_member(
                db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
            )
        projects.append(project)

    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    # The period is generated for a future week; pull its deadline behind us so it is now overdue.
    await db.execute(
        update(reporting_models.ReportingPeriod)
        .where(reporting_models.ReportingPeriod.id == period.id)
        .values(
            deadline_utc=now() - timedelta(hours=1), reminder_due_utc=now() - timedelta(minutes=1)
        )
    )
    return Week(period, projects)


def _entry(project_id: object) -> dict[str, object]:
    return {
        "project_id": project_id,
        "stage": "implementation",
        "work_performed": "Implemented the loader",
        "next_plan": {},
    }


async def test_the_student_who_did_not_submit_is_emailed(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, [student_a])

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    assert [n.recipient_id for n in sent] == [student_a.id]
    deliveries = (await db.execute(select(models.EmailDelivery))).scalars().all()
    assert [d.state for d in deliveries] == [models.DeliveryState.QUEUED]


async def test_a_submission_a_minute_before_the_deadline_gets_no_email(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-08: obligation state is read at send time, so a late-evening submission is seen.
    week = await _week(db, prof_scope, [student_a])
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db, scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    assert sent == []


async def test_an_excused_student_gets_no_email(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, [student_a])
    obligations = await reporting_service.list_obligations(db, prof_scope, week.period.id)
    await reporting_service.excuse_obligation(
        db, prof_scope, obligations[0].id, reason="Approved leave"
    )

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    assert sent == []


async def test_an_extension_still_running_gets_no_email(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, [student_a])
    obligations = await reporting_service.list_obligations(db, prof_scope, week.period.id)
    await reporting_service.extend_obligation(
        db, prof_scope, obligations[0].id, until=now() + timedelta(days=2), reason="Cluster outage"
    )

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    assert sent == []


async def test_a_partial_package_is_still_unfulfilled(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REP-08: an entry missing for one of two required projects yields one email naming it.
    week = await _week(db, prof_scope, [student_a], project_count=2)
    obligations = await reporting_service.list_obligations(db, prof_scope, week.period.id)
    second = next(o for o in obligations if o.project_id == week.projects[1].id)
    await reporting_service.excuse_obligation(db, prof_scope, second.id, reason="Paused")
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db, scope, period_id=week.period.id, entries=[_entry(week.projects[0].id)]
    )
    # Re-require the second project after the package was submitted without it.
    await db.execute(
        update(reporting_models.ReportingObligation)
        .where(reporting_models.ReportingObligation.id == second.id)
        .values(state=reporting_models.ObligationState.REQUIRED, excuse_reason=None)
    )

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    assert [n.recipient_id for n in sent] == [student_a.id]
    assert sent[0].payload["missing_projects"] == [
        {"id": str(week.projects[1].id), "title": "Project 1"}
    ]


async def test_running_the_job_again_sends_nothing_more(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-19: a retried job sends no duplicate.
    week = await _week(db, prof_scope, [student_a])

    first = await service.dispatch_missed_deadline(db, week.period.id)
    second = await service.dispatch_missed_deadline(db, week.period.id)

    assert len(first) == 1
    assert second == []
    rows = (
        (
            await db.execute(
                select(models.Notification).where(
                    models.Notification.kind == service.MISSED_DEADLINE
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_the_professor_is_told_in_app_who_is_outstanding(
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    week = await _week(db, prof_scope, [student_a])

    await service.dispatch_missed_deadline(db, week.period.id)

    professor_notifications = await service.list_notifications(db, prof_scope)
    summary = next(n for n in professor_notifications if n.kind == service.UNFULFILLED_OBLIGATIONS)
    assert summary.recipient_id == prof.id
    assert summary.payload["students"][0]["student_id"] == str(student_a.id)
    deliveries = (await db.execute(select(models.EmailDelivery))).scalars().all()
    assert all(d.notification_id != summary.id for d in deliveries), "the professor gets no email"


async def test_the_email_names_no_other_student(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # REP-08: the email contains no assessment content and no other student's information.
    week = await _week(db, prof_scope, [student_a, student_b])

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    for notification in sent:
        rendered = repr(notification.payload)
        other = student_b.id if notification.recipient_id == student_a.id else student_a.id
        assert str(other) not in rendered


async def test_the_period_records_that_the_reminder_was_dispatched(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, [student_a])

    await service.dispatch_missed_deadline(db, week.period.id)

    dispatched = (
        await db.execute(
            select(reporting_models.ReportingPeriod.reminder_dispatched_at).where(
                reporting_models.ReportingPeriod.id == week.period.id
            )
        )
    ).scalar_one()
    assert dispatched is not None


async def test_scanning_dispatches_every_period_whose_reminder_is_due(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await _week(db, prof_scope, [student_a])

    dispatched = await service.scan_due_reminders(db)

    assert [p for p in dispatched] == [week.period.id]
    assert await service.scan_due_reminders(db) == [], "a dispatched period is not picked up twice"


async def test_a_missed_deadline_notification_cannot_be_muted(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # A student must not be able to silence the one message that says they owe work.
    week = await _week(db, prof_scope, [student_a])
    scope = await identity_service.scope_for(db, student_a)
    with pytest.raises(ValidationError):
        await service.mute(db, scope, kind=service.MISSED_DEADLINE)

    sent = await service.dispatch_missed_deadline(db, week.period.id)

    assert [n.recipient_id for n in sent] == [student_a.id]
