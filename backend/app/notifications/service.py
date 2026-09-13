"""Notification use cases: in-app messages, preferences, reminders, and the missed-deadline email.

Requirements REP-07, REP-08, UI-07. Everything here is idempotent on a unique key, because the
worker may run any of it twice: a retried job must send nothing more (AC-19).

This module reads obligations and periods through reporting.service and users through
identity.service; it never queries their tables (docs/repo_layout.md §3.2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope, visible_to
from app.core.clock import now, to_utc
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.ids import uuid7
from app.identity import service as identity_service
from app.notifications import policies, repository  # noqa: F401  (policies register on import)
from app.notifications.email.base import EmailSender
from app.notifications.models import (
    DeliveryState,
    EmailDelivery,
    Notification,
    NotificationPreference,
    ReminderRule,
)
from app.notifications.schemas import NotificationOut, PreferenceOut
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
MILESTONE_OVERDUE = "milestone_overdue"
SYNC_FAILED = "sync_failed"

# A student must not be able to silence the message saying they owe work, nor the one saying the
# professor is waiting on a revision (architecture §13).
UNMUTABLE_KINDS = frozenset({MISSED_DEADLINE, REVISION_REQUESTED, UNFULFILLED_OBLIGATIONS})

MISSED_DEADLINE_TEMPLATE = "missed_deadline"
MAX_EMAIL_ATTEMPTS = 5


# ------------------------------------------------------------------ in-app notifications


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
    """Insert one notification, or return None when it is muted or already present.

    Called from jobs and event handlers that have no Scope of their own, so the recipient is named
    explicitly rather than derived from a caller.
    """
    if kind not in UNMUTABLE_KINDS and await repository.is_muted(session, recipient_id, kind):
        return None

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


async def list_notifications(
    session: AsyncSession, scope: Scope, *, unread_only: bool = False
) -> list[NotificationOut]:
    rows = await repository.list_notifications(session, scope, unread_only=unread_only)
    return [NotificationOut.model_validate(row) for row in rows]


async def unread_count(session: AsyncSession, scope: Scope) -> int:
    return await repository.unread_count(session, scope)


async def mark_read(session: AsyncSession, scope: Scope, notification_id: UUID) -> NotificationOut:
    notification = await repository.get_notification(session, scope, notification_id)
    if notification is None:
        raise NotFoundError("notification not found")
    if notification.read_at is None:
        notification.read_at = now()
        await session.flush()
    return NotificationOut.model_validate(notification)


async def mark_all_read(session: AsyncSession, scope: Scope) -> int:
    result = await session.execute(
        update(Notification)
        .where(visible_to(scope, Notification), Notification.read_at.is_(None))
        .values(read_at=now())
        .returning(Notification.id)
    )
    await session.flush()
    return len(result.scalars().all())


# ------------------------------------------------------------------ preferences (UI-07)


async def mute(session: AsyncSession, scope: Scope, *, kind: str) -> PreferenceOut:
    if kind in UNMUTABLE_KINDS:
        raise ValidationError(f"{kind} notifications cannot be muted")
    existing = await repository.get_preference(session, scope, kind)
    if existing is not None:
        return PreferenceOut.model_validate(existing)

    preference = NotificationPreference(
        workspace_id=scope.workspace_id, user_id=scope.user_id, kind=kind
    )
    session.add(preference)
    await session.flush()
    return PreferenceOut.model_validate(preference)


async def unmute(session: AsyncSession, scope: Scope, *, kind: str) -> None:
    existing = await repository.get_preference(session, scope, kind)
    if existing is not None:
        await session.delete(existing)
        await session.flush()


async def list_preferences(session: AsyncSession, scope: Scope) -> list[PreferenceOut]:
    rows = await repository.list_preferences(session, scope)
    return [PreferenceOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ reminders (REP-07)


async def set_reminder_offsets(
    session: AsyncSession, scope: Scope, *, offsets_hours: list[int]
) -> list[int]:
    """How long before the deadline an in-app reminder is raised, in whole hours."""
    scope.require_prof()
    if any(hours <= 0 for hours in offsets_hours):
        raise ValidationError("a reminder offset must be a positive number of hours")

    await repository.clear_reminder_rules(session, scope.workspace_id)
    wanted = sorted(set(offsets_hours), reverse=True)
    for hours in wanted:
        session.add(ReminderRule(workspace_id=scope.workspace_id, offset_minutes=hours * 60))
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
    """Reporting emits; notifications reacts, which is how reporting stays unaware of it.

    Registration happens on import, like the visibility policies, so any process that can notify
    has already wired it. `subscribe` is idempotent.
    """
    from app.reporting import events as reporting_events

    reporting_events.subscribe(reporting_events.ReportSubmitted, _on_report_submitted)
    reporting_events.subscribe(reporting_events.RevisionRequested, _on_revision_requested)


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
