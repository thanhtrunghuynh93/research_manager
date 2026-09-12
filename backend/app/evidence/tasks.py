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
        await service.sync_repository(
            session,
            system,
            row.id,
            connector=factory.build(row.provider, credential_ref=row.credential_ref),
            kind=SyncKind(kind),
        )
        await service.resolve_contributions(session, row.id)
        await session.commit()
