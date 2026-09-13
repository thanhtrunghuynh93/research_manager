"""AC-19 — The deadline passes with one student unsubmitted, one submitted at 23:58, and one on
approved leave | At 00:00 local time on the meeting day exactly one email goes to the unsubmitted
student, none to the others, and the professor sees the unfulfilled obligation in-app; a retried
job sends no duplicate.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now, reminder_due
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.notifications import service as notifications
from app.notifications.email.console import ConsoleEmailSender
from app.projects import service as projects_service
from app.reporting import models as reporting_models
from app.reporting import service as reporting_service
from tests.factories import make_user

pytestmark = pytest.mark.acceptance

TZ = "Asia/Ho_Chi_Minh"


async def test_ac_19_exactly_one_email_reaches_the_student_who_owes_a_report(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    prof: identity_models.User,
    prof_scope: Scope,
) -> None:
    unsubmitted = await make_user(db, workspace, email="unsubmitted@example.edu")
    on_time = await make_user(db, workspace, email="on-time@example.edu")
    on_leave = await make_user(db, workspace, email="on-leave@example.edu")

    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone=TZ,
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    for student in (unsubmitted, on_time, on_leave):
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
        )

    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    obligations = await reporting_service.ensure_obligations(db, prof_scope, period.id)

    # The third student is on approved leave for the week.
    excused = next(o for o in obligations if o.student_id == on_leave.id)
    await reporting_service.excuse_obligation(
        db, prof_scope, excused.id, reason="Approved leave: family event"
    )

    # The deadline has just passed; the second student submitted a minute before it.
    deadline = now() - timedelta(minutes=1)
    await db.execute(
        update(reporting_models.ReportingPeriod)
        .where(reporting_models.ReportingPeriod.id == period.id)
        .values(deadline_utc=deadline, reminder_due_utc=reminder_due(deadline))
    )
    submitter_scope = await identity_service.scope_for(db, on_time)
    await reporting_service.submit_report(
        db,
        submitter_scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Finished the loader",
                "next_plan": {},
            }
        ],
    )

    # 00:00 local on the meeting day: the periodic scan runs.
    dispatched = await notifications.scan_due_reminders(db)
    sender = ConsoleEmailSender()
    await notifications.send_queued_emails(db, sender)

    assert dispatched == [period.id]
    assert [email.to for email in sender.outbox] == ["unsubmitted@example.edu"]

    # The professor sees the outstanding obligation in the application, and receives no email.
    professor_messages = await notifications.list_notifications(db, prof_scope)
    summary = next(
        message
        for message in professor_messages
        if message.kind == notifications.UNFULFILLED_OBLIGATIONS
    )
    assert [entry["student_id"] for entry in summary.payload["students"]] == [str(unsubmitted.id)]
    assert prof.email not in [email.to for email in sender.outbox]

    # The student who submitted and the student on leave hear nothing.
    for student in (on_time, on_leave):
        scope = await identity_service.scope_for(db, student)
        kinds = [message.kind for message in await notifications.list_notifications(db, scope)]
        assert notifications.MISSED_DEADLINE not in kinds

    # A retried job sends no duplicate.
    assert await notifications.scan_due_reminders(db) == []
    await notifications.dispatch_missed_deadline(db, period.id)
    await notifications.send_queued_emails(db, sender)
    assert [email.to for email in sender.outbox] == ["unsubmitted@example.edu"]


async def test_ac_19_the_email_says_what_is_missing_and_nothing_else(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """The message lists the recipient's missing entries and the submit link, states the late or
    grace outcome, and contains no assessment content and no other student's information (REP-08).
    """
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone=TZ,
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    for student in (student_a, student_b):
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
        )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    await db.execute(
        update(reporting_models.ReportingPeriod)
        .where(reporting_models.ReportingPeriod.id == period.id)
        .values(deadline_utc=now() - timedelta(minutes=1))
    )

    await notifications.dispatch_missed_deadline(db, period.id)
    sender = ConsoleEmailSender()
    await notifications.send_queued_emails(db, sender)

    from app.notifications.templates import render

    for email in sender.outbox:
        subject, text, html = render(email.template, email.params["locale"], email.params)
        other = student_b.email if email.to == student_a.email else student_a.email
        assert "Baseline evaluation" in text
        assert f"/report/{period.id}" in text
        assert "late or within the grace" in text
        assert other not in text and other not in html
        assert subject.startswith("Weekly report not received")
