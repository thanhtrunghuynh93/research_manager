"""Periodic tasks that span modules (architecture §12).

Each module owns its own jobs — `notifications/scheduler_tasks.py`, `evidence/tasks.py`,
`assessment/tasks.py`. These four do not belong to any one of them: the calendar covers every
workspace, queue health reads the queue's own tables, and the retention sweep reaches from
records to object storage. They live at the application root for the same reason
`app/observability.py` does (docs/repo_layout.md §3.3).
"""

from __future__ import annotations

import logging

from app.core.db import session_factory
from app.core.jobs import procrastinate_app

log = logging.getLogger(__name__)


@procrastinate_app.periodic(cron="15 0 * * *")
@procrastinate_app.task(name="reporting.ensure_periods", queueing_lock="ensure_periods")
async def ensure_periods(timestamp: int = 0) -> None:
    """REP-01: keep the reporting calendar materialised eight weeks ahead.

    Without this the weekly cycle only exists when somebody remembers to ask for it, which is the
    kind of dependency on a person that the deadline rules exist to remove.
    """
    from app.reporting import service

    async with session_factory()() as session:
        created = await service.ensure_periods_everywhere(session)
        await session.commit()
    if created:
        log.info("reporting periods materialised: %s", created)


@procrastinate_app.periodic(cron="30 0 * * *")
@procrastinate_app.task(name="reporting.freeze_baselines", queueing_lock="freeze_baselines")
async def freeze_baselines(timestamp: int = 0) -> None:
    """PROJ-04: fix the plan each membership is assessed against, once its period has opened."""
    from app.reporting import service

    async with session_factory()() as session:
        frozen = await service.freeze_due_baselines(session)
        await session.commit()
    if frozen:
        log.info("plan baselines in effect: %s", frozen)


@procrastinate_app.periodic(cron="*/5 * * * *")
@procrastinate_app.task(name="ops.queue_health", queueing_lock="queue_health")
async def queue_health(timestamp: int = 0) -> None:
    """Refresh the gauges `/api/metrics` serves (architecture §12, §15 observability).

    Running it here rather than on the scrape means the numbers are the same whoever asks, and a
    scrape cannot become a load on the database.
    """
    from app import observability

    async with session_factory()() as session:
        summary = await observability.refresh(session)
    oldest = summary.get("queue", {}).get("oldest_seconds", 0)
    if oldest and oldest > 600:
        # Ten minutes is the assessment-latency budget in requirements §11; a job older than that
        # means the worker is behind, which nothing else would say out loud.
        log.warning("oldest queued job is %.0f s old", oldest)


@procrastinate_app.periodic(cron="45 1 * * *")
@procrastinate_app.task(name="ops.retention_sweep", queueing_lock="retention_sweep")
async def retention_sweep(timestamp: int = 0) -> None:
    """Expire what has a defined lifetime (requirements §11 "Data control").

    Only the answer cache has one today. Retention for reports, assessments and artifacts waits on
    the professor's retention policy, and inventing a schedule for deleting research records would
    be the wrong kind of initiative — the deletion is irreversible and the decision is theirs
    (requirements §14, implementation_status §5).
    """
    from app.assistant import cache
    from app.identity import service as identity_service

    removed = 0
    async with session_factory()() as session:
        for workspace_id in await identity_service.workspace_ids(session):
            epoch = await identity_service.access_epoch(session, workspace_id)
            removed += await cache.purge_stale(session, workspace_id, epoch)
        await session.commit()
    if removed:
        log.info("expired %s cached answer(s)", removed)
