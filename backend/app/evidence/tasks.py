"""Evidence worker jobs (architecture §12).

Thin wrappers, as every tasks.py is: open a session, call a service function that is already
idempotent, commit. `uq_repo_event (repository_id, provider_event_id)` is what makes a redelivered
webhook and a re-run sync range a no-op (REPO-05, AC-09), so at-least-once delivery is safe here.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.db import session_factory
from app.core.jobs import RETRY_TRANSIENT, procrastinate_app

log = logging.getLogger(__name__)


@procrastinate_app.periodic(cron="*/30 * * * *")
@procrastinate_app.task(name="evidence.incremental_sync", queueing_lock="incremental_sync")
async def incremental_sync(timestamp: int = 0) -> None:
    """REPO-05: pull what is new from every connected repository, every thirty minutes."""
    from app.evidence import service

    async with session_factory()() as session:
        outcomes = await service.sync_all_connected(session)
        await session.commit()

    for outcome in outcomes:
        if outcome.state == "completed":
            log.info("%s: %s event(s)", outcome.full_name, outcome.events_ingested)
        else:
            # Not an error in this process: the sync run carries the state, and the professor's
            # overview shows it as stale evidence rather than as an absence of work (AC-04).
            log.warning("%s: %s — %s", outcome.full_name, outcome.state, outcome.error or "")


@procrastinate_app.task(name="evidence.sync_repository", retry=RETRY_TRANSIENT)
async def sync_one(repository_id: str, kind: str = "manual") -> None:
    """A targeted run: the professor asked, or a webhook said this repository moved."""
    from app.core.authz import Scope
    from app.core.types import Role
    from app.evidence import service
    from app.evidence.connectors import factory
    from app.evidence.models import Repository, SyncKind

    async with session_factory()() as session:
        row = await session.get(Repository, UUID(repository_id))
        if row is None:
            log.warning("no repository %s to sync", repository_id)
            return
        system = Scope(
            workspace_id=row.workspace_id,
            user_id=row.connected_by or row.workspace_id,
            role=Role.PROF,
            project_ids=frozenset(),
            access_epoch=0,
        )
        run = await service.sync_repository(
            session,
            system,
            row.id,
            connector=factory.build(row.provider, credential_ref=row.credential_ref),
            kind=SyncKind(kind),
        )
        await service.resolve_contributions(session, row.id)
        await session.commit()

    if run.retry_after_seconds is not None:
        # The run is recorded; raising is what reaches RETRY_TRANSIENT. Without it a rate limit
        # left the remainder of the history waiting on the half-hourly sweep, which resumes from
        # the same watermark and so would not have fetched it anyway (REPO-05).
        from app.evidence.connectors.base import RateLimitedError

        raise RateLimitedError(
            f"{row.full_name} was rate limited", retry_after_seconds=run.retry_after_seconds
        )


@procrastinate_app.task(name="evidence.index_report_entries", retry=RETRY_TRANSIENT)
async def index_report_entries(report_version_id: str) -> None:
    """Index a submitted version's entries after an inline attempt failed (ASSESS-01, AC-13).

    The indexing normally happens inside the submitting transaction, so the chunks commit with the
    version they cite and the week's assessment reads a complete snapshot. That costs one call to
    the embedding provider on the student's critical path, and a provider that is down, rate
    limited or out of credit would otherwise take the submission with it — at 23:59, for every
    student at once.

    So the inline attempt is allowed to fail and this job picks the work up. `index_evidence`
    upserts the reference and replaces its chunks, which makes a re-run and a redelivered job the
    same thing; `RETRY_TRANSIENT` then gives the provider five attempts with backoff.

    The assessment drafted in the meantime may cite less than it could have. That is the
    recoverable half of the trade: coverage and confidence already describe an incomplete
    snapshot, and the professor can re-run the analysis. An unrecorded submission is not
    recoverable at all.
    """
    from app.evidence import service

    async with session_factory()() as session:
        indexed = await service.index_report_entries(session, UUID(report_version_id))
        await session.commit()
    log.info("indexed %s entr(ies) for report version %s", indexed, report_version_id)


@procrastinate_app.task(name="evidence.index_artifact_version", retry=RETRY_TRANSIENT)
async def index_artifact_version(version_id: str) -> None:
    """Index an attachment's extracted text after an inline attempt failed (REP-04, AC-13).

    The bytes and the extracted text are already in the object store by the time the inline attempt
    runs, so nothing the student did is lost and nothing has to be uploaded again — only the
    embedding call has to be repeated. `index_evidence` replaces the version's chunks, so a re-run
    and a redelivered job leave one copy.

    An attachment whose extraction found no text has nothing to index, and that is a no-op rather
    than a failure.
    """
    from app.evidence import service

    async with session_factory()() as session:
        indexed = await service.index_artifact_version(session, UUID(version_id))
        await session.commit()
    log.info("artifact version %s: %s", version_id, "indexed" if indexed else "nothing to index")
