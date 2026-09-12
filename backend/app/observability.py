"""Reading the current state into the metric gauges (architecture §12, §15).

Lives at the application root rather than in `app.core` because it reads across every module —
the queue, evidence, assessment, notifications — and `app.core` sits beneath all of them
(docs/repo_layout.md §3.3). The series themselves are declared in `app/core/metrics.py`, where any
module may increment a counter without reaching upward.

Every read is wrapped. Monitoring that can break the thing it monitors is worse than no monitoring.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics

log = logging.getLogger(__name__)


async def refresh(session: AsyncSession) -> dict[str, Any]:
    """Read the current state into the gauges. Never raises: monitoring must not break the worker.

    Counts are workspace-wide totals rather than per-workspace series. This deployment has one
    workspace, and a per-workspace label would become a way to enumerate them from the metrics
    endpoint if that ever changed.
    """
    summary: dict[str, Any] = {}
    for name, read in (
        ("queue", _queue),
        ("sync", _sync),
        ("assessment", _assessment),
        ("email", _email),
    ):
        try:
            summary[name] = await read(session)
        except Exception:  # noqa: BLE001 - a missing table or a permission is not worth a crash
            log.warning("could not refresh the %s metrics", name, exc_info=True)
            summary[name] = {}
    return summary


async def _queue(session: AsyncSession) -> dict[str, Any]:
    """procrastinate owns these tables, so they are read as SQL rather than through an ORM model."""
    rows = (
        await session.execute(
            text("SELECT status, count(*) FROM procrastinate_jobs GROUP BY status")
        )
    ).all()
    depths = {str(status): int(count) for status, count in rows}
    for status in ("todo", "doing", "succeeded", "failed", "cancelled", "aborted"):
        metrics.QUEUE_DEPTH.labels(status=status).set(depths.get(status, 0))

    oldest = (
        await session.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM (now() - min(scheduled_at))) "
                "FROM procrastinate_jobs WHERE status = 'todo'"
            )
        )
    ).scalar()
    metrics.QUEUE_OLDEST_SECONDS.set(float(oldest or 0))

    failures = (
        await session.execute(
            text(
                "SELECT task_name, count(*) FROM procrastinate_jobs "
                "WHERE status = 'failed' GROUP BY task_name"
            )
        )
    ).all()
    metrics.JOB_FAILURES.clear()
    for task_name, count in failures:
        metrics.JOB_FAILURES.labels(task=str(task_name)).set(int(count))

    return {"depth": depths, "oldest_seconds": float(oldest or 0)}


async def _sync(session: AsyncSession) -> dict[str, Any]:
    from app.evidence.models import ConnectionState, Repository, SyncRun, SyncState

    states = (
        await session.execute(
            select(Repository.connection_state, func.count(Repository.id)).group_by(
                Repository.connection_state
            )
        )
    ).all()
    counts = {str(state): int(count) for state, count in states}
    for state in ConnectionState:
        metrics.REPOSITORIES.labels(state=state.value).set(counts.get(state.value, 0))

    latest = (
        await session.execute(
            select(func.max(SyncRun.finished_at)).where(SyncRun.state == SyncState.COMPLETED)
        )
    ).scalar()
    if latest is not None:
        from app.core.clock import now

        metrics.SYNC_STALENESS_SECONDS.set((now() - latest).total_seconds())

    return {"repositories": counts, "last_successful_sync": latest}


async def _assessment(session: AsyncSession) -> dict[str, Any]:
    from app.assessment.models import AnalysisRun, AssessmentReview, AssessmentVersion, ReviewState

    runs = (
        await session.execute(
            select(AnalysisRun.state, func.count(AnalysisRun.id)).group_by(AnalysisRun.state)
        )
    ).all()
    counts = {str(state): int(count) for state, count in runs}
    metrics.ANALYSIS_RUNS.clear()
    for state, count in counts.items():
        metrics.ANALYSIS_RUNS.labels(state=state).set(count)

    versions = (await session.execute(select(func.count(AssessmentVersion.id)))).scalar_one()
    metrics.ASSESSMENT_VERSIONS.set(int(versions))

    queued = (
        await session.execute(
            select(func.count(AssessmentReview.id)).where(
                AssessmentReview.state == ReviewState.DRAFT
            )
        )
    ).scalar_one()
    metrics.REVIEW_QUEUE.set(int(queued))

    return {"runs": counts, "versions": int(versions), "review_queue": int(queued)}


async def _email(session: AsyncSession) -> dict[str, Any]:
    from app.notifications.models import EmailDelivery

    rows = (
        await session.execute(
            select(EmailDelivery.state, func.count(EmailDelivery.notification_id)).group_by(
                EmailDelivery.state
            )
        )
    ).all()
    counts = {str(state): int(count) for state, count in rows}
    metrics.EMAIL_DELIVERIES.clear()
    for state, count in counts.items():
        metrics.EMAIL_DELIVERIES.labels(state=state).set(count)
    return counts
