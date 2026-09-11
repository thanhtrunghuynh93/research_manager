"""Evidence use cases: connecting repositories, syncing them, and normalising what comes back.

Requirements REPO-01..08. Two rules shape everything here. Reprocessing a source event must change
nothing, so every write is keyed on the provider's own identifier (AC-09). And a repository that
cannot be read is a gap in coverage, never a claim that no work happened (AC-04).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import uuid7
from app.evidence import policies, repository as repo  # noqa: F401  (policies register on import)
from app.evidence.connectors.base import (
    AuthorizationError,
    CheckSummary,
    CommitMeta,
    ConnectorError,
    Issue,
    PullRequest,
    RepoRef,
    RepositoryConnector,
    Review,
)
from app.evidence.models import (
    ConnectionState,
    EventKind,
    ProjectRepository,
    Repository,
    RepositoryEvent,
    SyncKind,
    SyncRun,
    SyncState,
    WebhookDelivery,
)
from app.evidence.schemas import (
    EventOut,
    ProjectLinkOut,
    RepositoryOut,
    SyncRunOut,
    WebhookResult,
)
from app.projects import service as projects_service

log = logging.getLogger(__name__)

MAX_DIFF_BYTES = 40_000  # architecture §8.5: diff excerpts are capped per event


@dataclass
class _Progress:
    """What a sync achieved before it stopped, so a failure can still keep its ground."""

    ingested: int = 0
    pages: int = 0
    watermark: dict[str, Any] | None = None


# ------------------------------------------------------------------ connection (REPO-01)


async def connect_repository(
    session: AsyncSession,
    scope: Scope,
    *,
    provider: str,
    external_id: str,
    full_name: str,
    connector: RepositoryConnector,
    default_branch: str | None = None,
    credential_ref: str | None = None,
) -> RepositoryOut:
    """Record a repository the professor has granted read-only access to."""
    scope.require_prof()
    existing = await repo.get_by_external_id(session, scope.workspace_id, provider, external_id)
    if existing is not None:
        raise ConflictError("this repository is already connected")

    visibility = await connector.repo_visibility(
        RepoRef(provider=provider, external_id=external_id, full_name=full_name)  # type: ignore[arg-type]
    )
    repository = Repository(
        workspace_id=scope.workspace_id,
        provider=provider,
        external_id=external_id,
        full_name=full_name,
        visibility=visibility,
        connection_state=ConnectionState.CONNECTED,
        default_branch=default_branch,
        credential_ref=credential_ref,
        connected_by=scope.user_id,
    )
    session.add(repository)
    await session.flush()
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="repository.connected",
        target_table="repositories",
        target_id=repository.id,
        after={"full_name": full_name, "visibility": visibility},
    )
    return RepositoryOut.model_validate(repository)


async def link_project(
    session: AsyncSession,
    scope: Scope,
    repository_id: UUID,
    project_id: UUID,
    *,
    path_rules: list[str] | None = None,
) -> ProjectLinkOut:
    """REPO-04: map a repository to a project, with path rules when it serves several."""
    scope.require_prof()
    repository = await _require_repository(session, scope, repository_id)
    await projects_service.get_project(session, scope, project_id)

    existing = await repo.get_project_link(session, repository_id, project_id)
    if existing is not None:
        existing.path_rules = path_rules or existing.path_rules
        await session.flush()
        return ProjectLinkOut.model_validate(existing)

    link = ProjectRepository(
        workspace_id=repository.workspace_id,
        repository_id=repository_id,
        project_id=project_id,
        path_rules=path_rules or [],
    )
    session.add(link)
    await session.flush()
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="repository.linked_project",
        target_table="project_repositories",
        target_id=link.id,
        after={"project_id": str(project_id)},
    )
    return ProjectLinkOut.model_validate(link)


async def list_repositories(
    session: AsyncSession, scope: Scope, *, project_id: UUID | None = None
) -> list[RepositoryOut]:
    rows = await repo.list_repositories(session, scope, project_id=project_id)
    return [RepositoryOut.model_validate(row) for row in rows]


async def list_project_links(
    session: AsyncSession, scope: Scope, repository_id: UUID
) -> list[ProjectLinkOut]:
    rows = await repo.list_project_links(session, scope, repository_id)
    return [ProjectLinkOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ sync (REPO-05)


async def sync_repository(
    session: AsyncSession,
    scope: Scope,
    repository_id: UUID,
    *,
    connector: RepositoryConnector,
    kind: SyncKind | None = None,
) -> SyncRunOut:
    """Fetch what is new and normalise it, keeping whatever progress was made.

    A run ends `completed` when every page was read, `partial` when it stopped after progress (a
    rate limit, a bad page), and `failed` when it never got anywhere or the credential is gone
    (architecture §8.3).
    """
    repository = await _require_repository(session, scope, repository_id)
    previous = await repo.last_completed_run(session, repository_id)
    run_kind = kind or (SyncKind.INITIAL if previous is None else SyncKind.INCREMENTAL)
    watermark = dict(previous.watermark) if previous is not None else {}

    run = SyncRun(
        workspace_id=repository.workspace_id,
        repository_id=repository_id,
        kind=run_kind,
        state=SyncState.RUNNING,
        watermark=watermark,
        attempt=await repo.attempt_number(session, repository_id),
    )
    session.add(run)
    await session.flush()

    reference = RepoRef(
        provider=repository.provider,  # type: ignore[arg-type]
        external_id=repository.external_id,
        full_name=repository.full_name,
    )
    progress = _Progress(watermark=dict(watermark))

    try:
        await _sync_commits(session, repository, reference, connector, progress)
        await _sync_pull_requests(session, repository, reference, connector, progress)
        await _sync_issues(session, repository, reference, connector, progress)
    except AuthorizationError as error:
        # A person has to fix this; retrying the same credential cannot (REPO-05).
        repository.connection_state = ConnectionState.UNAUTHORIZED
        return await _finish(session, run, SyncState.FAILED, progress, str(error))
    except ConnectorError as error:
        state = SyncState.PARTIAL if progress.ingested or progress.pages else SyncState.FAILED
        return await _finish(session, run, state, progress, str(error))

    if repository.connection_state is ConnectionState.UNAUTHORIZED:
        repository.connection_state = ConnectionState.CONNECTED
    return await _finish(session, run, SyncState.COMPLETED, progress, None)


async def _finish(
    session: AsyncSession,
    run: SyncRun,
    state: SyncState,
    progress: _Progress,
    error: str | None,
) -> SyncRunOut:
    run.state = state
    run.watermark = progress.watermark or {}
    run.pages_done = progress.pages
    run.events_ingested = progress.ingested
    run.error_summary = error
    run.finished_at = now()
    await session.flush()
    if error:
        log.info("sync run %s ended %s: %s", run.id, state.value, error)
    return SyncRunOut.model_validate(run)


async def _sync_commits(
    session: AsyncSession,
    repository: Repository,
    reference: RepoRef,
    connector: RepositoryConnector,
    progress: _Progress,
) -> None:
    since = _watermark_time(progress.watermark, "commits_since")
    cursor: str | None = None
    while True:
        page = await connector.list_commits(reference, since, cursor)
        progress.pages += 1
        for commit in page.items:
            await _ingest_commit(session, repository, commit)
            progress.ingested += 1
            _advance(progress, "commits_since", commit.committed_at)
            # REPO-02: the CI summary for this commit, which is an observed external result.
            for check in await connector.list_check_runs(reference, commit.sha):
                await _ingest_check(session, repository, check, commit.sha)
                progress.ingested += 1
        if page.cursor is None:
            return
        cursor = page.cursor


async def _sync_pull_requests(
    session: AsyncSession,
    repository: Repository,
    reference: RepoRef,
    connector: RepositoryConnector,
    progress: _Progress,
) -> None:
    since = _watermark_time(progress.watermark, "prs_since")
    cursor: str | None = None
    while True:
        page = await connector.list_pull_requests(reference, since, cursor)
        progress.pages += 1
        for pull_request in page.items:
            await _ingest_pull_request(session, repository, pull_request)
            progress.ingested += 1
            _advance(progress, "prs_since", pull_request.updated_at)
            for review in await connector.list_reviews(reference, pull_request.number):
                await _ingest_review(session, repository, review)
                progress.ingested += 1
        if page.cursor is None:
            return
        cursor = page.cursor


async def _sync_issues(
    session: AsyncSession,
    repository: Repository,
    reference: RepoRef,
    connector: RepositoryConnector,
    progress: _Progress,
) -> None:
    since = _watermark_time(progress.watermark, "issues_since")
    cursor: str | None = None
    while True:
        page = await connector.list_issues(reference, since, cursor)
        progress.pages += 1
        for issue in page.items:
            await _ingest_issue(session, repository, issue)
            progress.ingested += 1
            _advance(progress, "issues_since", issue.updated_at)
        if page.cursor is None:
            return
        cursor = page.cursor


def _watermark_time(watermark: dict[str, Any] | None, field: str) -> datetime | None:
    raw = (watermark or {}).get(field)
    return datetime.fromisoformat(raw) if isinstance(raw, str) else None


def _advance(progress: _Progress, field: str, moment: datetime) -> None:
    current = _watermark_time(progress.watermark, field)
    if current is None or moment > current:
        progress.watermark = {**(progress.watermark or {}), field: moment.isoformat()}


# ------------------------------------------------------------------ normalisation (REPO-02)


async def _insert_event(session: AsyncSession, **values: Any) -> bool:
    """Insert one event, or do nothing if this source event is already recorded (AC-09)."""
    result = await session.execute(
        insert(RepositoryEvent)
        .values(id=uuid7(), **values)
        .on_conflict_do_nothing(index_elements=["repository_id", "provider_event_id"])
        .returning(RepositoryEvent.id)
    )
    inserted = result.scalar_one_or_none() is not None
    if inserted:
        await session.flush()
    return inserted


async def _ingest_commit(
    session: AsyncSession, repository: Repository, commit: CommitMeta
) -> None:
    await _insert_event(
        session,
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        provider_event_id=f"commit:{commit.sha}",
        kind=EventKind.COMMIT,
        source_version=commit.sha,
        title=commit.message.splitlines()[0] if commit.message else "",
        actors=[_actor(actor) for actor in commit.actors],
        authored_at=commit.authored_at,
        committed_at=commit.committed_at,
        event_at=commit.committed_at,
        paths=commit.paths,
        stats={
            "additions": commit.additions,
            "deletions": commit.deletions,
            "files": commit.files_changed,
        },
        source_url=f"https://github.com/{repository.full_name}/commit/{commit.sha}",
    )


async def _ingest_pull_request(
    session: AsyncSession, repository: Repository, pull_request: PullRequest
) -> None:
    merged = pull_request.merged_at is not None
    await _insert_event(
        session,
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        provider_event_id=f"pr:{pull_request.number}:{'merged' if merged else 'opened'}",
        kind=EventKind.PR_MERGED if merged else EventKind.PR_OPENED,
        source_version=pull_request.merge_commit_sha,
        title=pull_request.title,
        actors=[_actor(actor) for actor in pull_request.actors],
        merged_at=pull_request.merged_at,
        event_at=pull_request.merged_at or pull_request.created_at,
        stats={"number": pull_request.number, "state": pull_request.state},
        source_url=f"https://github.com/{repository.full_name}/pull/{pull_request.number}",
    )


async def _ingest_review(session: AsyncSession, repository: Repository, review: Review) -> None:
    await _insert_event(
        session,
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        provider_event_id=f"review:{review.external_id}",
        kind=EventKind.REVIEW,
        title=f"Review on #{review.pull_request_number}",
        actors=[_actor(review.actor)],
        event_at=review.submitted_at,
        stats={"state": review.state, "pull_request": review.pull_request_number},
        source_url=(
            f"https://github.com/{repository.full_name}/pull/{review.pull_request_number}"
            f"#pullrequestreview-{review.external_id}"
        ),
    )


async def _ingest_issue(session: AsyncSession, repository: Repository, issue: Issue) -> None:
    await _insert_event(
        session,
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        provider_event_id=f"issue:{issue.number}",
        kind=EventKind.ISSUE,
        title=issue.title,
        actors=[_actor(actor) for actor in issue.actors],
        event_at=issue.updated_at,
        stats={"number": issue.number, "state": issue.state},
        source_url=f"https://github.com/{repository.full_name}/issues/{issue.number}",
    )


async def _ingest_check(
    session: AsyncSession, repository: Repository, check: CheckSummary, sha: str
) -> None:
    """REPO-08: an observed external result. It does not prove the science is correct."""
    await _insert_event(
        session,
        workspace_id=repository.workspace_id,
        repository_id=repository.id,
        provider_event_id=f"check:{check.external_id}",
        kind=EventKind.CHECK_RUN,
        source_version=sha,
        title=check.name,
        actors=[],
        event_at=check.completed_at or now(),
        stats={"conclusion": check.conclusion},
        source_url=check.details_url,
    )


def _actor(actor: Any) -> dict[str, Any]:
    return {
        "role": actor.role,
        "login": actor.login,
        "email": actor.email,
        "name": actor.name,
        "is_bot": actor.is_bot,
    }


# ------------------------------------------------------------------ webhooks (REPO-05, AC-09)


async def ingest_webhook(
    session: AsyncSession,
    *,
    headers: dict[str, str],
    body: bytes,
    connector: RepositoryConnector,
) -> WebhookResult | None:
    """Verify, deduplicate, and record a delivery. Returns None when the signature does not hold.

    The delivery is only recorded here; the targeted sync it triggers is a job, so a slow provider
    call never holds the webhook response open.
    """
    event = connector.verify_webhook(headers, body)
    if event is None:
        log.warning("rejected a webhook delivery with an invalid signature")
        return None

    repository = await repo.get_by_external_id_any_workspace(
        session, event.provider, event.external_repo_id
    )
    inserted = await session.execute(
        insert(WebhookDelivery)
        .values(
            id=uuid7(),
            workspace_id=repository.workspace_id if repository else None,
            provider=event.provider,
            delivery_id=event.delivery_id,
            event=event.event,
            external_repo_id=event.external_repo_id,
        )
        .on_conflict_do_nothing(index_elements=["provider", "delivery_id"])
        .returning(WebhookDelivery.id)
    )
    if inserted.scalar_one_or_none() is None:
        return WebhookResult(
            accepted=False, delivery_id=event.delivery_id, detail="already delivered"
        )

    await session.flush()
    return WebhookResult(accepted=True, delivery_id=event.delivery_id)


async def record_force_push(
    session: AsyncSession,
    scope: Scope,
    repository_id: UUID,
    *,
    removed_versions: list[str],
    delivery_id: str,
) -> None:
    """REPO-06: keep the snapshot we were permitted to take, and say the live source is gone."""
    repository = await _require_repository(session, scope, repository_id)
    await repo.mark_versions_unavailable(session, repository_id, removed_versions)
    await _insert_event(
        session,
        workspace_id=repository.workspace_id,
        repository_id=repository_id,
        provider_event_id=f"push_force:{delivery_id}",
        kind=EventKind.PUSH_FORCE,
        title="History rewritten on the remote",
        actors=[],
        event_at=now(),
        stats={"removed_versions": removed_versions},
    )
    write_audit(
        session,
        workspace_id=repository.workspace_id,
        actor_id=scope.user_id,
        action="repository.force_push_recorded",
        target_table="repositories",
        target_id=repository_id,
        after={"removed_versions": removed_versions},
    )
    await session.flush()


# ------------------------------------------------------------------ reads


async def list_events(
    session: AsyncSession,
    scope: Scope,
    repository_id: UUID | None = None,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[EventOut]:
    rows = await repo.list_events(
        session, scope, repository_id=repository_id, since=since, until=until
    )
    return [EventOut.model_validate(row) for row in rows]


async def sync_status(
    session: AsyncSession, scope: Scope, repository_id: UUID
) -> SyncRunOut | None:
    await _require_repository(session, scope, repository_id)
    run = await repo.last_run(session, repository_id)
    return None if run is None else SyncRunOut.model_validate(run)


async def reset_watermark(session: AsyncSession, scope: Scope, repository_id: UUID) -> None:
    """A manual resync from the beginning; the idempotency keys make it safe (REPO-05)."""
    scope.require_prof()
    await _require_repository(session, scope, repository_id)
    await repo.clear_watermarks(session, repository_id)


async def _require_repository(
    session: AsyncSession, scope: Scope, repository_id: UUID
) -> Repository:
    repository = await repo.get_repository(session, scope, repository_id)
    if repository is None:
        raise NotFoundError("repository not found")
    return repository
