"""REPO-01/02/05/06: connecting a repository, syncing it, and what a sync is allowed to claim.

Reprocessing the same source event must not change anything, because the worker will do exactly
that: webhooks are delivered more than once and a partial run is retried (AC-09).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError, NotFoundError
from app.evidence import models, service
from app.evidence.connectors.base import (
    Actor,
    AuthorizationError,
    CheckSummary,
    CommitMeta,
    Issue,
    PullRequest,
    RateLimitedError,
    Review,
)
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.projects import service as projects_service

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def _commit(
    sha: str, *, authored: datetime, committed: datetime | None = None, **kwargs
) -> CommitMeta:
    return CommitMeta(
        sha=sha,
        message=kwargs.pop("message", f"Work on {sha}"),
        authored_at=authored,
        committed_at=committed or authored,
        actors=kwargs.pop("actors", [Actor(role="author", login="student-a")]),
        paths=kwargs.pop("paths", ["src/loader.py"]),
        additions=kwargs.pop("additions", 40),
        deletions=kwargs.pop("deletions", 3),
        files_changed=kwargs.pop("files_changed", 1),
    )


async def _project(db: AsyncSession, scope: Scope) -> object:
    project = await projects_service.create_project(
        db, scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, scope, project.id, status="active")
    return project


async def _connected(
    db: AsyncSession, scope: Scope, connector: FakeRepositoryConnector
) -> tuple[object, object]:
    project = await _project(db, scope)
    repository = await service.connect_repository(
        db,
        scope,
        provider="github",
        external_id="42",
        full_name="lab/baseline",
        connector=connector,
    )
    await service.link_project(db, scope, repository.id, project.id)
    return project, repository


async def test_connecting_records_the_repository_and_its_visibility(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # REPO-02: store source URLs, provider ids, and repository visibility.
    connector = FakeRepositoryConnector(visibility="private")

    _, repository = await _connected(db, prof_scope, connector)

    assert repository.provider == "github"
    assert repository.external_id == "42"
    assert repository.visibility == "private"
    assert repository.connection_state is models.ConnectionState.CONNECTED


async def test_only_the_professor_connects_a_repository(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    with pytest.raises(ForbiddenError):
        await service.connect_repository(
            db,
            student_a_scope,
            provider="github",
            external_id="42",
            full_name="lab/baseline",
            connector=FakeRepositoryConnector(),
        )


async def test_an_initial_sync_ingests_every_kind_of_event(
    db: AsyncSession, prof_scope: Scope
) -> None:
    connector = FakeRepositoryConnector(
        commits=[_commit("aaa", authored=WEEK), _commit("bbb", authored=WEEK + timedelta(hours=1))],
        pull_requests=[
            PullRequest(
                number=7,
                title="Add the loader",
                state="merged",
                created_at=WEEK,
                updated_at=WEEK + timedelta(hours=2),
                merged_at=WEEK + timedelta(hours=2),
                merge_commit_sha="ccc",
                actors=[
                    Actor(role="author", login="student-a"),
                    Actor(role="merger", login="prof"),
                ],
            )
        ],
        issues=[
            Issue(
                number=3,
                title="Loader drops the last split",
                state="open",
                created_at=WEEK,
                updated_at=WEEK,
                actors=[Actor(role="author", login="student-a")],
            )
        ],
        check_runs={
            "aaa": [
                CheckSummary(
                    external_id="c1", name="tests", conclusion="success", completed_at=WEEK
                )
            ]
        },
    )
    connector.reviews[7] = [
        Review(
            external_id="r1",
            pull_request_number=7,
            state="approved",
            submitted_at=WEEK + timedelta(hours=1, minutes=30),
            actor=Actor(role="reviewer", login="student-b"),
        )
    ]
    _, repository = await _connected(db, prof_scope, connector)

    run = await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    assert run.state is models.SyncState.COMPLETED
    events = await service.list_events(db, prof_scope, repository.id)
    kinds = {event.kind for event in events}
    assert kinds == {
        models.EventKind.COMMIT,
        models.EventKind.PR_MERGED,
        models.EventKind.REVIEW,
        models.EventKind.ISSUE,
        models.EventKind.CHECK_RUN,
    }


async def test_the_same_range_synced_again_creates_no_duplicate(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # AC-09: a retried sync range produces no duplicate event.
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)

    await service.sync_repository(db, prof_scope, repository.id, connector=connector)
    await service.reset_watermark(db, prof_scope, repository.id)
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    events = await service.list_events(db, prof_scope, repository.id)
    assert len([e for e in events if e.kind is models.EventKind.COMMIT]) == 1


async def test_pagination_walks_every_page(db: AsyncSession, prof_scope: Scope) -> None:
    connector = FakeRepositoryConnector(
        page_size=2,
        commits=[
            _commit(f"sha{index}", authored=WEEK + timedelta(minutes=index)) for index in range(5)
        ],
    )
    _, repository = await _connected(db, prof_scope, connector)

    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    events = await service.list_events(db, prof_scope, repository.id)
    assert len(events) == 5


async def test_the_watermark_means_the_next_sync_asks_for_less(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # REPO-05: incremental sync, so the second run does not re-read the whole history.
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)
    first = await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    connector.commits.append(_commit("bbb", authored=WEEK + timedelta(days=1)))
    second = await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    assert first.watermark.get("commits_since") is not None
    assert second.watermark["commits_since"] > first.watermark["commits_since"]
    assert len(await service.list_events(db, prof_scope, repository.id)) == 2


async def test_a_rate_limit_after_progress_leaves_the_run_partial(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # REPO-05 / architecture §8.3: keep what was fetched and retry from the last good page.
    connector = FakeRepositoryConnector(
        page_size=2,
        commits=[
            _commit(f"sha{index}", authored=WEEK + timedelta(minutes=index)) for index in range(6)
        ],
        rate_limit_after_pages=1,
    )
    _, repository = await _connected(db, prof_scope, connector)

    run = await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    assert run.state is models.SyncState.PARTIAL
    assert run.error_summary and "rate" in run.error_summary.lower()
    assert len(await service.list_events(db, prof_scope, repository.id)) == 2, "progress is kept"


async def test_an_authorization_failure_is_recorded_and_shown(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # AC-04: the dashboard identifies stale evidence; nothing infers that no work happened.
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)
    connector.fail_with = AuthorizationError("installation revoked")

    run = await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    assert run.state is models.SyncState.FAILED
    status = await service.sync_status(db, prof_scope, repository.id)
    assert status is not None
    assert status.state is models.SyncState.FAILED
    assert status.error_summary and "revoked" in status.error_summary
    stored = (
        await db.execute(select(models.Repository).where(models.Repository.id == repository.id))
    ).scalar_one()
    assert stored.connection_state is models.ConnectionState.UNAUTHORIZED


async def test_a_failed_sync_never_implies_an_absence_of_work(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # AC-04: a stale repository must not be read as zero work; the events already ingested stay.
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)
    connector.fail_with = RateLimitedError("slow down")

    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    assert len(await service.list_events(db, prof_scope, repository.id)) == 1


async def test_the_four_timestamps_are_kept_apart(db: AsyncSession, prof_scope: Scope) -> None:
    # REPO-06: author time, commit time, merge time, and ingestion time are not interchangeable.
    authored = WEEK - timedelta(days=20)
    committed = WEEK - timedelta(days=19)
    connector = FakeRepositoryConnector(
        commits=[_commit("old", authored=authored, committed=committed)],
        pull_requests=[
            PullRequest(
                number=9,
                title="Land the old work",
                state="merged",
                created_at=WEEK,
                updated_at=WEEK,
                merged_at=WEEK,
                merge_commit_sha="old",
                actors=[Actor(role="author", login="student-a")],
            )
        ],
    )
    _, repository = await _connected(db, prof_scope, connector)

    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    events = await service.list_events(db, prof_scope, repository.id)
    commit = next(e for e in events if e.kind is models.EventKind.COMMIT)
    merge = next(e for e in events if e.kind is models.EventKind.PR_MERGED)
    assert commit.authored_at == authored
    assert commit.committed_at == committed
    assert commit.authored_at != commit.committed_at
    assert merge.merged_at == WEEK
    assert commit.ingested_at > committed, "ingestion time is our clock, not theirs"


async def test_a_webhook_delivered_twice_is_ingested_once(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # AC-09: no duplicate event, contribution, notification, or score increase.
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)
    body = b'{"repository": {"id": 42}, "ref": "refs/heads/main"}'
    headers = {
        "X-GitHub-Delivery": "delivery-1",
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": connector.sign(body),
    }

    first = await service.ingest_webhook(db, headers=headers, body=body, connector=connector)
    second = await service.ingest_webhook(db, headers=headers, body=body, connector=connector)

    assert first is not None and first.accepted is True
    assert second is not None and second.accepted is False, "the delivery id is the guard"
    deliveries = (await db.execute(select(models.WebhookDelivery))).scalars().all()
    assert len(deliveries) == 1


async def test_a_webhook_with_a_bad_signature_is_refused(
    db: AsyncSession, prof_scope: Scope
) -> None:
    connector = FakeRepositoryConnector()
    await _connected(db, prof_scope, connector)
    body = b'{"repository": {"id": 42}}'

    result = await service.ingest_webhook(
        db,
        headers={"X-GitHub-Delivery": "d", "X-Hub-Signature-256": "sha256=wrong"},
        body=body,
        connector=connector,
    )

    assert result is None
    assert (await db.execute(select(models.WebhookDelivery))).first() is None


async def test_a_force_push_marks_the_live_source_unavailable(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # REPO-06: retain the permitted snapshot and mark the live source unavailable.
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.record_force_push(
        db, prof_scope, repository.id, removed_versions=["aaa"], delivery_id="force-1"
    )

    events = await service.list_events(db, prof_scope, repository.id)
    commit = next(e for e in events if e.source_version == "aaa")
    assert commit.live_available is False
    assert any(e.kind is models.EventKind.PUSH_FORCE for e in events)


async def test_an_ingested_event_cannot_be_rewritten(db: AsyncSession, prof_scope: Scope) -> None:
    connector = FakeRepositoryConnector(commits=[_commit("aaa", authored=WEEK)])
    _, repository = await _connected(db, prof_scope, connector)
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    with pytest.raises(Exception, match="immutable"):
        await db.execute(
            update(models.RepositoryEvent)
            .where(models.RepositoryEvent.repository_id == repository.id)
            .values(source_version="tampered")
        )
    await db.rollback()


async def test_a_repository_can_serve_several_projects(db: AsyncSession, prof_scope: Scope) -> None:
    # REPO-01: multiple repositories per project, and a repository may serve several projects.
    connector = FakeRepositoryConnector()
    first_project, repository = await _connected(db, prof_scope, connector)
    second_project = await projects_service.create_project(
        db, prof_scope, title="Theory", stage="theory"
    )

    await service.link_project(
        db, prof_scope, repository.id, second_project.id, path_rules=["theory/**"]
    )

    links = await service.list_project_links(db, prof_scope, repository.id)
    assert {link.project_id for link in links} == {first_project.id, second_project.id}


async def test_an_unknown_repository_is_not_found(db: AsyncSession, prof_scope: Scope) -> None:
    from uuid import uuid4

    with pytest.raises(NotFoundError):
        await service.sync_repository(db, prof_scope, uuid4(), connector=FakeRepositoryConnector())
