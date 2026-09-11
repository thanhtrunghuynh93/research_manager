"""The repository connector contract (REPO-01, architecture §8.1).

One provider is implemented for the MVP; the protocol is what keeps a second one a drop-in. Every
method is read-only: the system never writes to a repository and never executes its code (REPO-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

Provider = Literal["github", "gitlab"]
Visibility = Literal["private", "internal", "public"]
ActorRole = Literal["author", "committer", "reviewer", "merger"]


@dataclass(frozen=True, slots=True)
class RepoRef:
    """Where a repository lives at its provider, independent of our own identifiers."""

    provider: Provider
    external_id: str
    full_name: str


@dataclass(frozen=True, slots=True)
class Actor:
    """A person as the provider names them. Resolution to a student happens later (REPO-03)."""

    role: ActorRole
    login: str | None = None
    email: str | None = None
    name: str | None = None
    is_bot: bool = False


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CommitMeta:
    """REPO-06: author time and commit time are different facts and are kept apart."""

    sha: str
    message: str
    authored_at: datetime
    committed_at: datetime
    actors: list[Actor]
    paths: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    files_changed: int = 0
    parents: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DiffResult:
    sha: str
    text: str
    truncated: bool = False
    omitted_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    title: str
    state: Literal["open", "closed", "merged"]
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    merge_commit_sha: str | None
    actors: list[Actor]
    body: str = ""


@dataclass(frozen=True, slots=True)
class Review:
    external_id: str
    pull_request_number: int
    state: Literal["approved", "changes_requested", "commented", "dismissed"]
    submitted_at: datetime
    actor: Actor
    body: str = ""


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    title: str
    state: Literal["open", "closed"]
    created_at: datetime
    updated_at: datetime
    actors: list[Actor]
    body: str = ""


@dataclass(frozen=True, slots=True)
class CheckSummary:
    """REPO-08: an observed external test result, not proof that the science is correct."""

    external_id: str
    name: str
    conclusion: Literal["success", "failure", "neutral", "cancelled", "timed_out", "skipped"]
    completed_at: datetime | None
    details_url: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """A verified delivery. `delivery_id` is what makes a repeated delivery a no-op (AC-09)."""

    provider: Provider
    delivery_id: str
    event: str
    external_repo_id: str
    payload: dict[str, Any]


class ConnectorError(Exception):
    """Base for connector failures, so the sync loop can tell them apart (architecture §8.3)."""


class AuthorizationError(ConnectorError):
    """The credential no longer grants access; a retry cannot help until a person fixes it."""


class RateLimitedError(ConnectorError):
    """The provider asked us to slow down; progress so far is kept and the run is partial."""

    def __init__(self, detail: str = "", retry_after_seconds: int | None = None) -> None:
        super().__init__(detail or "rate limited")
        self.retry_after_seconds = retry_after_seconds


class RepositoryConnector(Protocol):
    provider: Provider

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None: ...

    async def repo_visibility(self, repo: RepoRef) -> Visibility: ...

    async def list_commits(
        self, repo: RepoRef, since: datetime | None, cursor: str | None
    ) -> Page[CommitMeta]: ...

    async def get_commit_diff(self, repo: RepoRef, sha: str, max_bytes: int) -> DiffResult: ...

    async def list_pull_requests(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[PullRequest]: ...

    async def list_reviews(self, repo: RepoRef, pr_number: int) -> list[Review]: ...

    async def list_issues(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[Issue]: ...

    async def list_check_runs(self, repo: RepoRef, sha: str) -> list[CheckSummary]: ...
