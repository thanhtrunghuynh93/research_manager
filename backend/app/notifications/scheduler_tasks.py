"""Periodic worker tasks (architecture §12).

Each task is a thin wrapper: it opens a session and calls a service function that is already
idempotent, so procrastinate's at-least-once delivery is safe. The job key is the queueing lock,
so a second queued job with the same key is refused.
"""

from __future__ import annotations

import logging

from app.core.clock import now
from app.core.config import get_settings
from app.core.db import session_factory
from app.core.jobs import key, procrastinate_app
from app.notifications import service
from app.notifications.email.console import ConsoleEmailSender
from app.notifications.email.smtp import SmtpEmailSender

log = logging.getLogger(__name__)


def email_sender() -> object:
    """SMTP in every environment that configured a host; the console sender in development."""
    settings = get_settings()
    if settings.env == "dev" and not settings.smtp_user and settings.smtp_host in ("", "localhost"):
        return ConsoleEmailSender()
    return SmtpEmailSender(settings)


@procrastinate_app.periodic(cron="*/5 * * * *")
@procrastinate_app.task(name="notifications.scan_due_reminders", queueing_lock="scan_reminders")
async def scan_due_reminders(timestamp: int = 0) -> None:
    """REP-08: find periods whose reminder is due and dispatch them."""
    async with session_factory()() as session:
        dispatched = await service.scan_due_reminders(session)
        await session.commit()
    if dispatched:
        log.info("dispatched missed-deadline notifications for %s period(s)", len(dispatched))


@procrastinate_app.task(name="notifications.dispatch_missed_deadline")
async def dispatch_missed_deadline(period_id: str) -> None:
    """REP-08: evaluate obligations now and notify whoever is still unfulfilled."""
    from uuid import UUID

    async with session_factory()() as session:
        await service.dispatch_missed_deadline(session, UUID(period_id), at=now())
        await session.commit()


@procrastinate_app.periodic(cron="*/2 * * * *")
@procrastinate_app.task(name="notifications.send_queued_emails", queueing_lock="send_emails")
async def send_queued_emails(timestamp: int = 0) -> None:
    """Deliver what is queued. A failure leaves the row for the next pass until the cap."""
    async with session_factory()() as session:
        sent = await service.send_queued_emails(session, email_sender())  # type: ignore[arg-type]
        await session.commit()
    if sent:
        log.info("sent %s email(s)", sent)


@procrastinate_app.periodic(cron="*/15 * * * *")
@procrastinate_app.task(name="notifications.dispatch_due_reminders", queueing_lock="pre_reminders")
async def dispatch_due_reminders(timestamp: int = 0) -> None:
    """REP-07: the configurable in-app reminders before the deadline."""
    async with session_factory()() as session:
        await service.dispatch_due_reminders(session)
        await session.commit()


def missed_deadline_key(period_id: object) -> str:
    return key("missed", period_id)
