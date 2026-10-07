"""Queries over the notification tables only. Other modules' data arrives through their services."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import DeliveryState, EmailDelivery, Notification


async def notification_row(session: AsyncSession, notification_id: UUID) -> Notification | None:
    """Job-level read: the sender acts for the system and has no Scope."""
    return await session.get(Notification, notification_id)


async def queued_deliveries(session: AsyncSession, *, limit: int) -> list[EmailDelivery]:
    return list(
        (
            await session.execute(
                select(EmailDelivery)
                .where(EmailDelivery.state == DeliveryState.QUEUED)
                .order_by(EmailDelivery.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def failed_delivery_count(session: AsyncSession, workspace_id: UUID) -> int:
    return (
        await session.execute(
            select(func.count(EmailDelivery.notification_id)).where(
                EmailDelivery.workspace_id == workspace_id,
                EmailDelivery.state == DeliveryState.FAILED,
            )
        )
    ).scalar_one()


async def failed_token_email_count(session: AsyncSession) -> int:
    """Invitation and recovery emails that exhausted their retries.

    These deliberately bypass `email_deliveries` (architecture §6.2): a token message has no in-app
    counterpart, and a queue row would hold a live credential until the next sweep. The cost is
    that the delivery table cannot see them, so the queue is the only place the failure exists —
    and an invitation nobody received is an account nobody can reach.

    Not scoped to a workspace, because the job carries an address rather than a workspace: the row
    is an operational fact about this deployment, not a record about one workspace's users. The
    count is of jobs, so one address that failed twice counts twice; the number is a prompt to go
    and look, not a population.
    """
    count = (
        await session.execute(
            text(
                "SELECT count(*) FROM procrastinate_jobs "
                "WHERE task_name = 'notifications.send_token_email' AND status = 'failed'"
            )
        )
    ).scalar_one()
    return int(count)
