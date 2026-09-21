"""Notification use cases: message records, reminders, and the missed-deadline email.

Requirements REP-07, REP-08, UI-07. Everything here is idempotent on a unique key, because the
worker may run any of it twice: a retried job must send nothing more (AC-19).

This module reads obligations and periods through reporting.service and users through
identity.service; it never queries their tables (docs/repo_layout.md §3.2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now, to_utc
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.ids import uuid7
from app.core.jobs import defer_after_commit
from app.identity import security
from app.identity import service as identity_service
from app.notifications import policies, repository  # noqa: F401  (policies register on import)
from app.notifications.email.base import EmailSender
from app.notifications.models import (
    DeliveryState,
    EmailDelivery,
    Notification,
    ReminderRule,
)
from app.notifications.schemas import NotificationOut
from app.reporting import service as reporting_service

log = logging.getLogger(__name__)

# The kind vocabulary (UI-07). Pre-deadline reminders add `reminder:{n}h` at runtime.
REPORT_SUBMITTED = "report_submitted"
REPORT_RESUBMITTED = "report_resubmitted"
REVISION_REQUESTED = "revision_requested"
DEADLINE_APPROACHING = "deadline_approaching"
MISSED_DEADLINE = "missed_deadline"
UNFULFILLED_OBLIGATIONS = "unfulfilled_obligations"
ASSESSMENT_RELEASED = "assessment_released"
SYNC_FAILED = "sync_failed"

MISSED_DEADLINE_TEMPLATE = "missed_deadline"
# AUTH-01: the two messages that carry a credential rather than news.
INVITATION_TEMPLATE = "invitation"
PASSWORD_RESET_TEMPLATE = "password_reset"  # noqa: S105 - a template name, not a secret
MAX_EMAIL_ATTEMPTS = 5


# ------------------------------------------------------------------ notification records


async def notify(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    recipient_id: UUID,
    kind: str,
    subject_table: str,
    subject_id: UUID | None = None,
    period_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> NotificationOut | None:
    """Insert one notification, or return None when the same one already exists.

    Called from jobs and event handlers that have no Scope of their own, so the recipient is named
    explicitly rather than derived from a caller.

    There is no mute check: use cases v0.3 retired preferences, so every notification a job raises
    is recorded. Whether it also leaves the building is the delivery layer's question, not this
    one's.
    """
    created = (
        await session.execute(
            insert(Notification)
            .values(
                id=uuid7(),
                workspace_id=workspace_id,
                recipient_id=recipient_id,
                kind=kind,
                subject_table=subject_table,
                subject_id=subject_id,
                period_id=period_id,
                payload=payload or {},
            )
            .on_conflict_do_nothing()
            .returning(Notification)
        )
    ).scalar_one_or_none()
    if created is None:
        return None  # the same message already exists; a retry adds nothing
    await session.flush()
    return NotificationOut.model_validate(created)


# ------------------------------------------------------------------ reminders (REP-07)


async def set_reminder_offsets(
    session: AsyncSession, scope: Scope, *, offsets_hours: list[int]
) -> list[int]:
    """How long before the deadline an in-app reminder is raised, in whole hours.

    Workspace-wide and last-writer-wins: with co-equal professors (ADR 0011) one overwrites the
    other's schedule, so the change is audited with what it replaced. Two people need to be able
    to answer "who changed this"; they do not need a lock.
    """
    scope.require_prof()
    if any(hours <= 0 for hours in offsets_hours):
        raise ValidationError("a reminder offset must be a positive number of hours")

    before = sorted(
        (
            rule.offset_minutes // 60
            for rule in await repository.reminder_rules(session, scope.workspace_id)
        ),
        reverse=True,
    )
    await repository.clear_reminder_rules(session, scope.workspace_id)
    wanted = sorted(set(offsets_hours), reverse=True)
    for hours in wanted:
        session.add(ReminderRule(workspace_id=scope.workspace_id, offset_minutes=hours * 60))
    write_audit(
        session,
        scope=scope,
        action="workspace.reminder_offsets_set",
        target_table="reminder_rules",
        target_id=scope.workspace_id,
        before={"offsets_hours": before},
        after={"offsets_hours": wanted},
    )
    await session.flush()
    return wanted


async def dispatch_due_reminders(
    session: AsyncSession, *, at: datetime | None = None
) -> list[NotificationOut]:
    """REP-07: raise in-app reminders for obligations still unfulfilled inside an offset window.

    The window opens at `deadline - offset` and closes at the deadline; the unique index keeps one
    reminder per recipient, period, and offset however often the scan runs.

    Each rule applies to its own workspace only. Both reads here are job-level and unscoped, so
    matching them by time alone let one professor's offsets reach another professor's students —
    including a workspace that had deliberately configured none (REP-07).
    """
    instant = at or now()
    raised: list[NotificationOut] = []

    for rule in await repository.all_reminder_rules(session):
        offset = timedelta(minutes=rule.offset_minutes)
        periods = await reporting_service.periods_with_deadline_between(
            session, start=instant, end=instant + offset, workspace_id=rule.workspace_id
        )
        for period in periods:
            kind = reminder_kind(rule.offset_minutes)
            for student_id, missing in _group_by_student(
                await reporting_service.unfulfilled_entries(session, period.id, at=instant)
            ).items():
                created = await notify(
                    session,
                    workspace_id=rule.workspace_id,
                    recipient_id=student_id,
                    kind=kind,
                    subject_table="reporting_periods",
                    subject_id=period.id,
                    period_id=period.id,
                    payload={
                        "deadline_utc": period.deadline_utc.isoformat(),
                        "missing_projects": missing,
                    },
                )
                if created is not None:
                    raised.append(created)
    return raised


def reminder_kind(offset_minutes: int) -> str:
    hours, minutes = divmod(offset_minutes, 60)
    return f"reminder:{hours}h" if minutes == 0 else f"reminder:{offset_minutes}m"


# ------------------------------------------------------------------ missed deadline (REP-08)


async def scan_due_reminders(session: AsyncSession, *, at: datetime | None = None) -> list[UUID]:
    """The periodic scan: dispatch every period whose reminder is due and not yet dispatched."""
    instant = at or now()
    dispatched: list[UUID] = []
    for period in await reporting_service.periods_awaiting_reminder(session, at=instant):
        await dispatch_missed_deadline(session, period.id, at=instant)
        dispatched.append(period.id)
    return dispatched


async def dispatch_missed_deadline(
    session: AsyncSession, period_id: UUID, *, at: datetime | None = None
) -> list[NotificationOut]:
    """REP-08: notify every student whose obligation for this period is still unfulfilled.

    The obligations are read here, at the moment of sending, so a submission at 23:59 is seen and
    receives nothing (AC-19). Every write is keyed, so running the job again inserts nothing and
    therefore sends nothing.
    """
    instant = at or now()
    period = await reporting_service.period_for_job(session, period_id)
    if period is None:
        raise NotFoundError("reporting period not found")

    unfulfilled = _group_by_student(
        await reporting_service.unfulfilled_entries(session, period_id, at=instant)
    )
    timezone = await reporting_service.period_timezone(session, period_id)
    deadline_local = _deadline_local(period.meeting_date, timezone)
    settings = get_settings()
    created: list[NotificationOut] = []

    for student_id, missing in unfulfilled.items():
        contact = await identity_service.contact_for_job(session, student_id)
        if contact is None:
            continue
        notification = await notify(
            session,
            workspace_id=contact.workspace_id,
            recipient_id=student_id,
            kind=MISSED_DEADLINE,
            subject_table="reporting_periods",
            subject_id=period_id,
            period_id=period_id,
            payload={
                "period_start": period.local_start.isoformat(),
                "period_end": period.local_end.isoformat(),
                "deadline_utc": period.deadline_utc.isoformat(),
                "deadline_local": deadline_local,
                "missing_projects": missing,
                "submit_url": f"{settings.public_url}/report/{period_id}",
            },
        )
        if notification is None:
            continue
        created.append(notification)
        session.add(
            EmailDelivery(
                notification_id=notification.id,
                workspace_id=notification.workspace_id,
                recipient_email=contact.email,
                template=MISSED_DEADLINE_TEMPLATE,
                state=DeliveryState.QUEUED,
            )
        )
        await session.flush()

    if unfulfilled:
        await _notify_professors(session, period, unfulfilled)

    # Stamped last, so a crash before this point leaves the period to be retried harmlessly.
    await reporting_service.mark_reminder_dispatched(session, period_id, at=instant)
    return created


async def _notify_professors(
    session: AsyncSession, period: Any, unfulfilled: dict[UUID, list[dict[str, str]]]
) -> None:
    """REP-08: the professor sees the list in-app at the same time, and receives no email."""
    students = [
        {"student_id": str(student_id), "missing_projects": missing}
        for student_id, missing in unfulfilled.items()
    ]
    workspace_id = await _workspace_of(session, next(iter(unfulfilled)))
    for professor_id in await identity_service.professor_ids(session, workspace_id):
        await notify(
            session,
            workspace_id=workspace_id,
            recipient_id=professor_id,
            kind=UNFULFILLED_OBLIGATIONS,
            subject_table="reporting_periods",
            subject_id=period.id,
            period_id=period.id,
            payload={
                "period_start": period.local_start.isoformat(),
                "period_end": period.local_end.isoformat(),
                "students": students,
            },
        )


def _group_by_student(entries: list[Any]) -> dict[UUID, list[dict[str, str]]]:
    """One message per student, naming only that student's own missing entries (REP-08)."""
    grouped: dict[UUID, list[dict[str, str]]] = {}
    for entry in entries:
        grouped.setdefault(entry.student_id, []).append(
            {"id": str(entry.project_id), "title": entry.project_title}
        )
    return grouped


def _deadline_local(meeting_date: Any, timezone: str) -> str:
    """The deadline as the recipient reads it: 23:59 local on the day before the meeting."""
    from datetime import timedelta as _timedelta

    from app.core.clock import DEADLINE_LOCAL_TIME

    day = meeting_date - _timedelta(days=1)
    to_utc(day, DEADLINE_LOCAL_TIME, timezone)  # validates the timezone
    return f"{day.isoformat()} 23:59 ({timezone})"


async def _workspace_of(session: AsyncSession, user_id: UUID) -> UUID:
    contact = await identity_service.contact_for_job(session, user_id)
    if contact is None:
        raise NotFoundError("user not found")
    return contact.workspace_id


# ------------------------------------------------------------------ email delivery


async def send_queued_emails(session: AsyncSession, sender: EmailSender, *, limit: int = 50) -> int:
    """Send what is queued, with bounded retries. The in-app message stands either way."""
    sent = 0
    for delivery in await repository.queued_deliveries(session, limit=limit):
        notification = await repository.notification_row(session, delivery.notification_id)
        if notification is None:
            continue
        contact = await identity_service.contact_for_job(session, notification.recipient_id)
        params = {
            **notification.payload,
            "display_name": contact.display_name if contact else "",
        }
        result = await sender.send(
            delivery.recipient_email,
            delivery.template,
            params,
            idempotency_key=str(delivery.notification_id),
        )
        delivery.attempts += 1
        if result.accepted:
            delivery.state = DeliveryState.SENT
            delivery.sent_at = now()
            sent += 1
        else:
            delivery.last_error = result.detail[:1000]
            if delivery.attempts >= MAX_EMAIL_ATTEMPTS:
                # The professor's overview surfaces a failed delivery; the notification remains.
                delivery.state = DeliveryState.FAILED
            log.warning(
                "email delivery %s failed on attempt %s: %s",
                delivery.notification_id,
                delivery.attempts,
                result.detail,
            )
        await session.flush()
    return sent


async def failed_deliveries(session: AsyncSession, scope: Scope) -> int:
    """UI-01: the professor's overview shows a mail-delivery warning rather than silence."""
    scope.require_prof()
    return await repository.failed_delivery_count(session, scope.workspace_id)


@dataclass(frozen=True)
class MailHealth:
    """What is wrong with mail, split by how it would be noticed.

    The two counts are kept apart because the professor's response differs. A failed notification
    is an inconvenience — the in-app message is still there and the recipient can still sign in. A
    failed token email is an enrolment that did not happen: the addressee has no session, no in-app
    counterpart exists, and there is no other way into an invitation-only system (AUTH-01).
    """

    failed_notifications: int
    failed_token_emails: int

    @property
    def warning(self) -> bool:
        return bool(self.failed_notifications or self.failed_token_emails)

    @property
    def reason(self) -> str:
        if not self.warning:
            return ""
        parts = []
        if self.failed_token_emails:
            parts.append(
                f"{self.failed_token_emails} invitation or recovery email(s) were never "
                "delivered; those people cannot sign in until the link is reissued"
            )
        if self.failed_notifications:
            parts.append(f"{self.failed_notifications} notification email(s) failed to send")
        return "; ".join(parts)


async def mail_health(session: AsyncSession, scope: Scope) -> MailHealth:
    """UI-01, production-readiness §1.1: mail failure the professor can actually see.

    Before this, a misconfigured relay produced a roll that still read "Invitation sent to …"
    while the job died in the queue, and nobody learned the student was never contacted.
    """
    scope.require_prof()
    return MailHealth(
        failed_notifications=await repository.failed_delivery_count(session, scope.workspace_id),
        failed_token_emails=await repository.failed_token_email_count(session),
    )


# ------------------------------------------------------------------ reactions to other modules


async def _on_report_submitted(event: Any, session: AsyncSession) -> None:
    """UI-07: tell the professor a package arrived. The message carries no report content."""
    for professor_id in await identity_service.professor_ids(session, event.workspace_id):
        await notify(
            session,
            workspace_id=event.workspace_id,
            recipient_id=professor_id,
            kind=REPORT_RESUBMITTED if event.resubmitted else REPORT_SUBMITTED,
            subject_table="report_versions",
            subject_id=event.report_version_id,
            payload={
                "student_id": str(event.student_id),
                "period_id": str(event.period_id),
                "report_id": str(event.report_id),
            },
        )


def register_subscriptions() -> None:
    """Reporting and identity emit; notifications reacts, which is how they stay unaware of it.

    Registration happens on import, like the visibility policies, so any process that can notify
    has already wired it. `subscribe` is idempotent.
    """
    from app.identity import events as identity_events
    from app.reporting import events as reporting_events

    reporting_events.subscribe(reporting_events.ReportSubmitted, _on_report_submitted)
    reporting_events.subscribe(reporting_events.RevisionRequested, _on_revision_requested)
    identity_events.subscribe(identity_events.InvitationCreated, _on_invitation_created)
    identity_events.subscribe(identity_events.PasswordResetRequested, _on_password_reset_requested)


# ------------------------------------------------------------------ token emails (AUTH-01)


async def _defer_token_email(
    session: AsyncSession,
    *,
    template: str,
    workspace_id: UUID,
    email: str,
    display_name: str,
    token: str,
    expires_at: datetime,
    path: str,
) -> None:
    """AUTH-01: send the one channel the token travels on, once the issuing transaction commits.

    Deferred rather than sent inline. A handler runs inside the emitting transaction, which has
    flushed but not committed, so talking to a mail provider here would announce an invitation
    that a later rollback erases (app.identity.events).

    The link is assembled here rather than in the template because `public_url` is what the
    recipient's browser can actually reach, and only the settings know it.
    """
    from app.notifications import scheduler_tasks

    settings = get_settings()
    workspace = await identity_service.workspace_for_job(session, workspace_id)
    defer_after_commit(
        session,
        scheduler_tasks.send_token_email,
        template=template,
        to=email,
        params={
            "display_name": display_name,
            "workspace_name": workspace.name if workspace else "your research workspace",
            "link": f"{settings.public_url}{path}?token={token}",
            "expires_at": expires_at.date().isoformat(),
            # One key per token: a redelivered event is the same email, and a reissued
            # invitation is a different one.
            "idempotency_key": security.hash_token(token),
        },
    )


async def _on_invitation_created(event: Any, session: AsyncSession) -> None:
    """AUTH-01: the invitation link reaches the invited mailbox, and nowhere else."""
    await _defer_token_email(
        session,
        template=INVITATION_TEMPLATE,
        workspace_id=event.workspace_id,
        email=event.email,
        display_name=event.display_name,
        token=event.token,
        expires_at=event.expires_at,
        path="/accept-invitation",
    )


async def _on_password_reset_requested(event: Any, session: AsyncSession) -> None:
    """AUTH-01: account recovery for every user, through the address on record."""
    await _defer_token_email(
        session,
        template=PASSWORD_RESET_TEMPLATE,
        workspace_id=event.workspace_id,
        email=event.email,
        display_name=event.display_name,
        token=event.token,
        expires_at=event.expires_at,
        path="/reset-password",
    )


async def _on_revision_requested(event: Any, session: AsyncSession) -> None:
    """REP-07/UI-07: the student is told which entry to revise, and cannot mute it.

    The subject is the request, not the report. Under `(recipient, period, kind)` alone the second
    revision request of a week — a different project, or a second round on the same one — collided
    with the first and was silently dropped, for the one kind a student is not allowed to mute.
    """
    await notify(
        session,
        workspace_id=event.workspace_id,
        recipient_id=event.student_id,
        kind=REVISION_REQUESTED,
        subject_table="revision_requests",
        subject_id=event.request_id,
        period_id=event.period_id,
        payload={
            "report_id": str(event.report_id),
            "project_id": str(event.project_id) if event.project_id else None,
            "reason": event.reason,
        },
    )


register_subscriptions()
