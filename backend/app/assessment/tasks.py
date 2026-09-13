"""The assessment pipeline as a worker job (architecture §9.1, §12).

Thin by design: it opens a session and calls the service, which is already idempotent on the
subject. procrastinate delivers at least once, and the queueing lock plus the pipeline's own check
on `content_changed_in_version_id` mean a redelivery produces no second draft.

A failure here is a state rather than a crash. `run_pipeline` records the run as `partial` or
`delayed_budget` and returns; the report and its timestamp are untouched, the review queue shows
the reason, and the professor can retry (AC-13).
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.db import session_factory
from app.core.jobs import RETRY_TRANSIENT, procrastinate_app

log = logging.getLogger(__name__)


@procrastinate_app.task(name="assessment.run_assessment", retry=RETRY_TRANSIENT)
async def run_assessment(
    student_id: str,
    project_id: str,
    period_id: str,
    report_version_id: str | None = None,
) -> None:
    """Produce the draft for one student, project and week."""
    from app.assessment import service

    async with session_factory()() as session:
        assessment = await service.run_pipeline(
            session,
            student_id=UUID(student_id),
            project_id=UUID(project_id),
            period_id=UUID(period_id),
            report_version_id=UUID(report_version_id) if report_version_id else None,
        )
        await session.commit()

    if assessment is None:
        # Either nothing had changed, or the run stopped short and recorded why. Both are
        # ordinary outcomes; `analysis_runs` carries the distinction.
        log.info(
            "no new draft for student %s project %s period %s",
            student_id,
            project_id,
            period_id,
        )
    else:
        log.info("draft assessment %s created (version %s)", assessment.id, assessment.version_no)
