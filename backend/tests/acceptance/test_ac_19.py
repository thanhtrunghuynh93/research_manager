"""AC-19 — The deadline passes with one student unsubmitted, one submitted at 23:58, and one on
approved leave | At 00:00 local time on the meeting day exactly one email goes to the unsubmitted
student, none to the others, and the professor sees the unfulfilled obligation in-app; a retried
job sends no duplicate.

Amended in 0.12: "in-app" is the overview's outstanding list (UI-01), read from the obligations.
The notification record the job used to write for the professor had no screen to appear on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now, reminder_due
from app.identity import models as identity_models
from app.notifications import service as notifications
from app.notifications.email.console import ConsoleEmailSender
from app.notifications.models import Notification
from app.overview import service as overview_service
from app.reporting import models as reporting_models
from app.reporting import service as reporting_service
from tests.factories import make_entry, make_user, make_week, submit

pytestmark = pytest.mark.acceptance


async def test_ac_19_exactly_one_email_reaches_the_student_who_owes_a_report(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    prof: identity_models.User,
    prof_scope: Scope,
    frozen_now: Callable[[datetime], None],
) -> None:
    # Inside the week of 14 September, the one this scenario is about. Left to the wall clock,
    # saving the calendar opens every week up to today and their reminders come due too.
    frozen_now(datetime(2026, 9, 15, 3, 0, tzinfo=UTC))
    unsubmitted = await make_user(db, workspace, email="unsubmitted@example.edu")
    on_time = await make_user(db, workspace, email="on-time@example.edu")
    on_leave = await make_user(db, workspace, email="on-leave@example.edu")

    week = await make_week(
        db, prof_scope, [unsubmitted, on_time, on_leave], title="Baseline evaluation"
    )
    period = week.period
    obligations = await reporting_service.list_obligations(db, prof_scope, period.id)

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
    await submit(
        db, on_time, week, make_entry(week.project.id, work="Finished the loader", next_plan={})
    )

    # 00:00 local on the meeting day: the periodic scan runs.
    dispatched = await notifications.scan_due_reminders(db)
    sender = ConsoleEmailSender()
    await notifications.send_queued_emails(db, sender)

    assert dispatched == [period.id]
    assert [email.to for email in sender.outbox] == ["unsubmitted@example.edu"]

    # The professor sees the outstanding obligation on the overview, and receives no email.
    outstanding = await overview_service.missing_reports(db, prof_scope, as_of=now())
    assert outstanding is not None
    assert [entry["student_id"] for entry in outstanding] == [str(unsubmitted.id)]
    assert prof.email not in [email.to for email in sender.outbox]

    # The student who submitted and the student on leave hear nothing.
    recipients = (await db.execute(select(Notification.recipient_id))).scalars().all()
    assert on_time.id not in recipients
    assert on_leave.id not in recipients

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
    week = await make_week(db, prof_scope, [student_a, student_b], title="Baseline evaluation")
    period = week.period
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
        subject, text, html = render(email.template, email.params)
        other = student_b.email if email.to == student_a.email else student_a.email
        assert "Baseline evaluation" in text
        assert f"/report/{period.id}" in text
        assert "late or within the grace" in text
        assert other not in text and other not in html
        assert subject.startswith("Weekly report not received")
