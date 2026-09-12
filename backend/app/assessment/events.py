"""What `assessment` does when a report arrives (architecture §9.1, docs/repo_layout.md §3.2).

This is the seam that makes the product run unattended. `reporting` emits `ReportSubmitted` and
knows nothing about assessment; this module subscribes and enqueues one pipeline job per project
entry whose content actually moved.

Two rules live in the enqueue rather than in the pipeline, because they decide whether a job is
created at all:

  - one job per *entry*, not per package, since one weekly submission covering two projects
    produces two separate assessments (AC-01);
  - nothing for an entry carried forward unchanged, since revising one project's entry must not
    re-assess another (AC-17). The pipeline checks this again from the database, but not creating
    the job is cheaper and makes the queue readable.

An enqueue that fails must not take the report with it. The submitted version is the thing that
cannot be lost (requirements §10, AC-13); a missing draft is recoverable from the professor's
retry endpoint, and an unrecorded submission is not recoverable at all.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import defer_after_commit, key
from app.reporting import service as reporting_service

log = logging.getLogger(__name__)


def pipeline_key(
    *, student_id: UUID, project_id: UUID, period_id: UUID, report_version_id: UUID | None
) -> str:
    """`assess:{student}:{project}:{period}:{version}` — the queueing lock (architecture §12).

    procrastinate refuses a second queued job with the same lock, so a redelivered event and a
    manual retry are the same job rather than two drafts.
    """
    return key("assess", student_id, project_id, period_id, report_version_id or "none")


async def defer_pipeline(
    *,
    session: AsyncSession,
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
    report_version_id: UUID,
) -> None:
    """Record the enqueue; it is sent once the caller's transaction commits.

    Deferring inline would let the worker dequeue this job and look for a report version that has
    not committed yet, and would leave the job behind if the submission rolled back (app.core.jobs).
    """
    from app.assessment import tasks

    defer_after_commit(
        session,
        tasks.run_assessment,
        queueing_lock=pipeline_key(
            student_id=student_id,
            project_id=project_id,
            period_id=period_id,
            report_version_id=report_version_id,
        ),
        student_id=str(student_id),
        project_id=str(project_id),
        period_id=str(period_id),
        report_version_id=str(report_version_id),
    )


async def _on_report_submitted(event: Any, session: AsyncSession) -> None:
    entries = await reporting_service.entries_for_indexing(
        session, report_version_id=event.report_version_id
    )
    for entry in entries:
        assessable = await reporting_service.entry_for_assessment(
            session, report_version_id=event.report_version_id, project_id=entry.project_id
        )
        if assessable is None:
            continue
        if assessable.changed_in_version_id != event.report_version_id:
            # Carried forward untouched: its existing assessment still describes it (AC-17).
            log.debug("entry for project %s unchanged; no assessment enqueued", entry.project_id)
            continue

        try:
            await defer_pipeline(
                session=session,
                student_id=event.student_id,
                project_id=entry.project_id,
                period_id=event.period_id,
                report_version_id=event.report_version_id,
            )
        except Exception:  # noqa: BLE001 - the submitted version is what must survive
            log.exception(
                "could not enqueue the assessment for student %s project %s; the report is "
                "recorded and the professor can retry the analysis",
                event.student_id,
                entry.project_id,
            )


def register_subscriptions() -> None:
    """Called on import, like the visibility policies, so any process that submits has it wired."""
    from app.reporting import events as reporting_events

    reporting_events.subscribe(reporting_events.ReportSubmitted, _on_report_submitted)


register_subscriptions()
