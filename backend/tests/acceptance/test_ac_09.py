"""AC-09 — A webhook is delivered twice and the same sync range is retried | No duplicate event,
contribution, notification, or score increase occurs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.clock import now
from app.evidence import models as evidence_models
from app.evidence import service as evidence_service
from app.evidence.connectors.base import Actor, CommitMeta
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from app.notifications import models as notification_models
from app.notifications import service as notifications
from app.reporting import models as reporting_models

pytestmark = pytest.mark.acceptance

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


async def test_ac_09_nothing_is_counted_twice(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User, week_for
) -> None:
    week = await week_for(db, prof_scope, student_a)
    connector = FakeRepositoryConnector(
        commits=[
            CommitMeta(
                sha="aaa",
                message="Add the loader",
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
    await evidence_service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )

    # The same webhook delivery arrives twice.
    body = b'{"repository": {"id": 42}, "ref": "refs/heads/main"}'
    headers = {
        "X-GitHub-Delivery": "delivery-1",
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": connector.sign(body),
    }
    first = await evidence_service.ingest_webhook(
        db, headers=headers, body=body, connector=connector
    )
    second = await evidence_service.ingest_webhook(
        db, headers=headers, body=body, connector=connector
    )
    assert first is not None and first.accepted
    assert second is not None and not second.accepted

    # And the same range is synced twice.
    await evidence_service.sync_repository(db, prof_scope, repository.id, connector=connector)
    await evidence_service.reset_watermark(db, prof_scope, repository.id)
    await evidence_service.sync_repository(db, prof_scope, repository.id, connector=connector)
    await evidence_service.resolve_contributions(db, repository.id)
    await evidence_service.resolve_contributions(db, repository.id)

    events = await evidence_service.list_events(db, prof_scope, repository.id)
    assert len([e for e in events if e.kind is evidence_models.EventKind.COMMIT]) == 1
    assert len(await evidence_service.list_contributions(db, prof_scope)) == 1
    assert (
        await evidence_service.distinct_event_count(db, prof_scope, project_id=week.projects[0].id)
        == 1
    )

    # And the missed-deadline job runs twice.
    await db.execute(
        update(reporting_models.ReportingPeriod)
        .where(reporting_models.ReportingPeriod.id == week.period.id)
        .values(deadline_utc=now() - timedelta(minutes=1))
    )
    await notifications.dispatch_missed_deadline(db, week.period.id)
    await notifications.dispatch_missed_deadline(db, week.period.id)

    sent = (
        (
            await db.execute(
                select(notification_models.Notification).where(
                    notification_models.Notification.kind == notifications.MISSED_DEADLINE
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sent) == 1
