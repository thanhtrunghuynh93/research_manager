"""AC-04 — A repository connection fails during the reporting week | Report submission succeeds;
the dashboard identifies stale evidence; no zero-work inference is made.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.evidence import models as evidence_models
from app.evidence import service as evidence_service
from app.evidence.connectors.base import Actor, AuthorizationError, CommitMeta
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from tests.factories import make_week, submit

pytestmark = pytest.mark.acceptance

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


async def test_ac_04_a_broken_connection_blocks_nothing_and_claims_nothing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    week = await make_week(db, prof_scope, [student_a])
    connector = FakeRepositoryConnector(
        commits=[
            CommitMeta(
                sha="aaa",
                message="Work before the outage",
                authored_at=WEEK,
                committed_at=WEEK,
                actors=[Actor(role="author", login="student-a")],
                paths=["src/loader.py"],
            )
        ]
    )
    repository = await evidence_service.connect_repository(
        db,
        prof_scope,
        provider="github",
        external_id="42",
        full_name="lab/baseline",
        connector=connector,
    )
    await evidence_service.link_project(db, prof_scope, repository.id, week.projects[0].id)
    await evidence_service.sync_repository(db, prof_scope, repository.id, connector=connector)

    # The installation is revoked mid-week.
    connector.fail_with = AuthorizationError("installation revoked")
    run = await evidence_service.sync_repository(db, prof_scope, repository.id, connector=connector)

    # The report still submits: acceptance never waits on a repository (requirements §10).
    version = await submit(db, student_a, week)
    assert version.version_no == 1

    # The dashboard can say the evidence is stale, and why.
    assert run.state is evidence_models.SyncState.FAILED
    status = await evidence_service.sync_status(db, prof_scope, repository.id)
    assert status is not None and "revoked" in (status.error_summary or "")

    # What was already collected is still there: a failed sync is not an absence of work.
    events = await evidence_service.list_events(db, prof_scope, repository.id)
    assert [e.source_version for e in events] == ["aaa"]
