"""Operator commands for notifications, registered in app.cli as `notifications`.

These exist for the case the runbook covers: the mail provider was misconfigured, the deadline
passed, and the professor needs the dispatch run again once it is fixed. Running it a second time
is safe by construction — the notification key and the delivery row make a repeat a no-op — which
is what makes it something an operator may do without thinking hard (architecture §12, AC-19).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import run_in_session
from app.notifications import service
from app.notifications.scheduler_tasks import email_sender

cli = typer.Typer(no_args_is_help=True, help="Notification and email operations")


@cli.command("dispatch-missed-deadline")
def dispatch_missed_deadline(
    period: Annotated[UUID, typer.Option("--period", help="The reporting period to evaluate")],
) -> None:
    """Evaluate the obligations now and notify whoever is still unfulfilled (REP-08)."""

    async def _run(session: AsyncSession) -> tuple[int, int]:
        created = await service.dispatch_missed_deadline(session, period)
        sent = await service.send_queued_emails(session, email_sender())  # type: ignore[arg-type]
        return len(created), sent

    created, sent = run_in_session(_run)
    typer.echo(f"notifications created: {created}; emails sent: {sent}")


@cli.command("send-queued-emails")
def send_queued_emails(
    limit: Annotated[int, typer.Option("--limit", help="Queued deliveries to attempt")] = 50,
) -> None:
    """Drain the email queue once, for when the periodic task is not running."""

    async def _run(session: AsyncSession) -> int:
        return await service.send_queued_emails(session, email_sender(), limit=limit)  # type: ignore[arg-type]

    typer.echo(f"emails sent: {run_in_session(_run)}")
