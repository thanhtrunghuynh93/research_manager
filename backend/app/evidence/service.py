"""Evidence use cases: connecting repositories, syncing them, and normalising what comes back.

Requirements REPO-01..08. Two rules shape everything here. Reprocessing a source event must change
nothing, so every write is keyed on the provider's own identifier (AC-09). And a repository that
cannot be read is a gap in coverage, never a claim that no work happened (AC-04).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.ids import uuid7
from app.evidence import policies  # noqa: F401  (policies register on import)
from app.evidence import repository as repo
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
    AttributionState,
    ConnectionState,
    Contribution,
    ContributionRole,
    ContributionShare,
    DeveloperIdentity,
    EventKind,
    IdentityVerification,
    ProjectRepository,
    Repository,
    RepositoryEvent,
    SyncKind,
    SyncRun,
    SyncState,
    WebhookDelivery,
)
from app.evidence.schemas import (
    ContributionOut,
    EventOut,
    IdentityOut,
    ProjectLinkOut,
    RepositoryOut,
    SyncRunOut,
    WebhookResult,
)
from app.identity import service as identity_service
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


async def _ingest_commit(session: AsyncSession, repository: Repository, commit: CommitMeta) -> None:
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


# ------------------------------------------------------------------ identity mapping (REPO-03)


async def map_identity(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID,
    provider: str = "github",
    login: str | None = None,
    email: str | None = None,
    verification: IdentityVerification | None = None,
) -> IdentityOut:
    """Record that a provider account belongs to a student.

    A student may claim their own account; only the professor may map someone else's. A login the
    professor sets is confirmed by them, while an email alias starts pending, because an address in
    a commit trailer proves nothing on its own (REPO-03).
    """
    if not scope.is_prof and student_id != scope.user_id:
        raise ForbiddenError("only the professor maps another person's account")
    if login is None and email is None:
        raise ValidationError("an identity needs a login or an email address")

    await identity_service.get_user(session, scope, student_id)
    existing = await repo.find_identity(session, scope.workspace_id, provider, login, email)
    if existing is not None and existing.student_id != student_id:
        raise ConflictError("that provider account is already mapped to another student")

    state = verification or (
        IdentityVerification.CONFIRMED_BY_PROF
        if scope.is_prof and login
        else IdentityVerification.PENDING
    )
    if existing is not None:
        existing.verification = state
        await session.flush()
        return IdentityOut.model_validate(existing)

    identity = DeveloperIdentity(
        workspace_id=scope.workspace_id,
        student_id=student_id,
        provider=provider,
        login=login,
        email=email,
        verification=state,
        is_bot=_looks_like_a_bot(login),
        confirmed_by=scope.user_id if state is not IdentityVerification.PENDING else None,
    )
    session.add(identity)
    await session.flush()
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="developer_identity.mapped",
        target_table="developer_identities",
        target_id=identity.id,
        after={"student_id": str(student_id), "login": login, "email": email},
    )
    return IdentityOut.model_validate(identity)


async def confirm_identity(session: AsyncSession, scope: Scope, identity_id: UUID) -> IdentityOut:
    """REPO-03: the explicit confirmation that turns a claim into an attribution."""
    identity = await repo.get_identity(session, scope, identity_id)
    if identity is None:
        raise NotFoundError("developer identity not found")
    if not scope.is_prof and identity.student_id != scope.user_id:
        raise ForbiddenError("only the professor confirms another person's account")

    identity.verification = (
        IdentityVerification.CONFIRMED_BY_PROF
        if scope.is_prof
        else IdentityVerification.CONFIRMED_BY_STUDENT
    )
    identity.confirmed_by = scope.user_id
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="developer_identity.confirmed",
        target_table="developer_identities",
        target_id=identity.id,
        after={"verification": identity.verification.value},
    )
    await session.flush()
    return IdentityOut.model_validate(identity)


async def list_identities(
    session: AsyncSession, scope: Scope, *, student_id: UUID | None = None
) -> list[IdentityOut]:
    rows = await repo.list_identities(session, scope, student_id=student_id)
    return [IdentityOut.model_validate(row) for row in rows]


def _looks_like_a_bot(login: str | None) -> bool:
    return bool(login and (login.endswith("[bot]") or login.endswith("-bot")))


# ------------------------------------------------------------------ attribution (REPO-04, AC-06)

ATTRIBUTING_ROLES = {
    ContributionRole.AUTHOR,
    ContributionRole.COMMITTER,
    ContributionRole.REVIEWER,
    ContributionRole.MERGER,
}
RESOLVING_VERIFICATIONS = {
    IdentityVerification.VERIFIED_OAUTH,
    IdentityVerification.CONFIRMED_BY_STUDENT,
    IdentityVerification.CONFIRMED_BY_PROF,
}


async def resolve_contributions(
    session: AsyncSession, repository_id: UUID, *, since: datetime | None = None
) -> int:
    """REPO-04: turn each event's actors into contributions, saying how sure each one is.

    Runs in the worker, so it takes no Scope. Every row is keyed on (event, student, role), which
    is what stops a reprocessed event from increasing anyone's contributions (AC-09).
    """
    events = await repo.events_for_attribution(session, repository_id, since=since)
    links = await repo.links_for_repository(session, repository_id)
    identities = await repo.identities_for_repository_workspace(session, repository_id)
    written = 0

    for event in events:
        if event.kind is EventKind.PUSH_FORCE:
            continue
        actors = [actor for actor in event.actors if not actor.get("is_bot")]
        authors = [a for a in actors if a.get("role") in ("author", "committer")]
        share = (
            ContributionShare.JOINT
            if len({_actor_key(a) for a in authors}) > 1
            else ContributionShare.INDIVIDUAL
        )

        for actor in actors:
            role = _role_of(actor)
            if role is None:
                continue
            identity = _match_identity(identities, actor)
            if identity is None:
                continue  # an unrecognised account is left unresolved rather than guessed at

            project_id, state = _project_for(event, links)
            written += await _record_contribution(
                session,
                event=event,
                student_id=identity.student_id,
                role=role,
                # Only authorship can be shared; a review or a merge is its own act.
                share=share
                if role in (ContributionRole.AUTHOR, ContributionRole.COMMITTER)
                else ContributionShare.INDIVIDUAL,
                project_id=project_id,
                attribution_state=state,
                provenance={
                    "matched_on": "login" if actor.get("login") else "email",
                    "value": actor.get("login") or actor.get("email"),
                    "verification": identity.verification.value,
                    "source_version": event.source_version,
                },
            )
    await session.flush()
    return written


def _actor_key(actor: dict[str, Any]) -> str:
    return str(actor.get("login") or actor.get("email") or actor.get("name") or "")


def _role_of(actor: dict[str, Any]) -> ContributionRole | None:
    try:
        role = ContributionRole(actor.get("role", ""))
    except ValueError:
        return None
    return role if role in ATTRIBUTING_ROLES else None


def _match_identity(
    identities: list[DeveloperIdentity], actor: dict[str, Any]
) -> DeveloperIdentity | None:
    """REPO-03: only a verified login or a confirmed alias attributes anything."""
    login = (actor.get("login") or "").lower()
    email = (actor.get("email") or "").lower()
    for identity in identities:
        if identity.verification not in RESOLVING_VERIFICATIONS or identity.is_bot:
            continue
        if login and (identity.login or "").lower() == login:
            return identity
        if email and (identity.email or "").lower() == email:
            return identity
    return None


def _project_for(
    event: RepositoryEvent, links: list[ProjectRepository]
) -> tuple[UUID | None, AttributionState]:
    """REPO-04: one project needs no rules.

    Several need a rule that matches exactly one project, or nothing is claimed for the event.
    """
    if not links:
        return None, AttributionState.UNRESOLVED_PROJECT
    if len(links) == 1:
        return links[0].project_id, AttributionState.RESOLVED

    matched = {
        link.project_id
        for link in links
        for rule in link.path_rules
        if any(fnmatch(path, rule) for path in event.paths)
    }
    if len(matched) == 1:
        return matched.pop(), AttributionState.RESOLVED
    return None, AttributionState.UNRESOLVED_PROJECT


async def _record_contribution(
    session: AsyncSession,
    *,
    event: RepositoryEvent,
    student_id: UUID,
    role: ContributionRole,
    share: ContributionShare,
    project_id: UUID | None,
    attribution_state: AttributionState,
    provenance: dict[str, Any],
) -> int:
    result = await session.execute(
        insert(Contribution)
        .values(
            id=uuid7(),
            workspace_id=event.workspace_id,
            event_id=event.id,
            student_id=student_id,
            project_id=project_id,
            role=role,
            share=share,
            attribution_state=attribution_state,
            provenance=provenance,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "student_id", "role"])
        .returning(Contribution.id)
    )
    return 1 if result.scalar_one_or_none() is not None else 0


async def list_contributions(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
) -> list[ContributionOut]:
    rows = await repo.list_contributions(
        session, scope, student_id=student_id, project_id=project_id
    )
    return [ContributionOut.model_validate(row) for row in rows]


async def distinct_event_count(session: AsyncSession, scope: Scope, *, project_id: UUID) -> int:
    """AC-06: a project counts a shared artifact once, however many students share it."""
    return await repo.distinct_contributed_events(session, scope, project_id=project_id)


async def unresolved_actors(session: AsyncSession, scope: Scope, repository_id: UUID) -> list[str]:
    """REPO-03: the accounts nobody has claimed, so the professor can map or dismiss them."""
    await _require_repository(session, scope, repository_id)
    identities = await repo.identities_for_repository_workspace(session, repository_id)
    known = {(i.login or "").lower() for i in identities} | {
        (i.email or "").lower() for i in identities
    }
    unknown: set[str] = set()
    for event in await repo.events_for_attribution(session, repository_id):
        for actor in event.actors:
            if actor.get("is_bot"):
                continue
            key = _actor_key(actor)
            if key and key.lower() not in known:
                unknown.add(key)
    return sorted(unknown)


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
