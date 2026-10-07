"""Reading the current state into the metric gauges (architecture §12, §15).

Lives at the application root rather than in `app.core` because it reads across every module —
the queue, assessment, notifications — and `app.core` sits beneath all of them
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
    """Read the current state into the gauges. Never raises: monitoring must not break the api.

    Called by `/api/metrics` (throttled there), in the process that serves the gauges — they live
    in that process's memory, so filling them anywhere else would fill nobody's scrape.

    Counts are workspace-wide totals rather than per-workspace series. This deployment has one
    workspace, and a per-workspace label would become a way to enumerate them from the metrics
    endpoint if that ever changed.
    """
    summary: dict[str, Any] = {}
    for name, read in (
        ("queue", _queue),
        ("assessment", _assessment),
        ("email", _email),
    ):
        try:
            summary[name] = await read(session)
        except Exception:  # noqa: BLE001 - a missing table or a permission is not worth a crash
            log.warning("could not refresh the %s metrics", name, exc_info=True)
            summary[name] = {}
    return summary


# How long a finished job stays in the queue's tables. Seven days because that is also how long an
# invitation link lives (`identity.security.INVITATION_TTL`): a failed invitation email older than
# that carried a link that has expired anyway, so dropping it from the mail warning loses nothing.
FINISHED_JOB_RETENTION_DAYS = 7


async def purge_finished_jobs(session: AsyncSession, *, older_than_days: int) -> int:
    """Delete jobs that finished more than `older_than_days` ago; return how many.

    Without this `procrastinate_jobs` and `procrastinate_events` grow by a few hundred rows a day
    forever — every five-minute heartbeat is a job. "Finished" is the job's last event, the same
    test procrastinate's own `delete_old_jobs` uses. The events go with the job (`ON DELETE
    CASCADE`), and procrastinate's own trigger unlinks any periodic-defer row pointing at it.
    """
    deleted = await session.execute(
        text(
            "DELETE FROM procrastinate_jobs j "
            "WHERE j.status IN ('succeeded', 'failed', 'cancelled', 'aborted') "
            "AND (SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id) "
            "< now() - make_interval(days => :days)"
        ),
        {"days": older_than_days},
    )
    return int(deleted.rowcount or 0)  # type: ignore[attr-defined]


async def oldest_queued_seconds(session: AsyncSession) -> float:
    """How long the oldest `todo` job has been waiting, in seconds; 0 when nothing waits."""
    # `scheduled_at` is NULL for every job deferred without a delay, which is nearly all of them,
    # and min() skips NULLs — so a backlog of thousands of immediately-deferred jobs reported an
    # age of zero and the "worker is behind" warning could never fire. The `deferred` event
    # carries when the job was actually enqueued, which is what "waiting how long" means.
    oldest = (
        await session.execute(
            text(
                "SELECT EXTRACT(EPOCH FROM (now() - min(COALESCE(j.scheduled_at, e.at)))) "
                "FROM procrastinate_jobs j "
                "LEFT JOIN LATERAL ("
                "  SELECT min(at) AS at FROM procrastinate_events"
                "  WHERE job_id = j.id AND type = 'deferred'"
                ") e ON TRUE "
                "WHERE j.status = 'todo'"
            )
        )
    ).scalar()
    return float(oldest or 0)


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

    oldest = await oldest_queued_seconds(session)
    metrics.QUEUE_OLDEST_SECONDS.set(oldest)

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

    return {"depth": depths, "oldest_seconds": oldest}


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
