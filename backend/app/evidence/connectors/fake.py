"""In-memory connector for tests, the demo seed, and the end-to-end stack.

The product must remain fully usable without a repository (REPO-01), and the pipeline must be
provable without reaching GitHub, so this is a first-class implementation rather than a mock: it
paginates, it can be told to fail or rate-limit, and it enforces the same read-only contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.evidence.connectors.base import (
    AuthorizationError,
    CheckSummary,
    CommitMeta,
    DiffResult,
    Issue,
    Page,
    Provider,
    PullRequest,
    RateLimitedError,
    RepoRef,
    Review,
    Visibility,
    WebhookEvent,
)


@dataclass
class FakeRepositoryConnector:
    """Scripted provider state. Every list method paginates at `page_size`."""

    provider: Provider = "github"
    page_size: int = 2
    webhook_secret: str = "fake-secret"  # noqa: S105 - test double
    visibility: Visibility = "private"

    commits: list[CommitMeta] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)
    reviews: dict[int, list[Review]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    check_runs: dict[str, list[CheckSummary]] = field(default_factory=dict)
    diffs: dict[str, str] = field(default_factory=dict)

    # Faults the sync loop must survive (architecture §8.3).
    fail_with: Exception | None = None
    rate_limit_after_pages: int | None = None
    # GitHub pages commits, pull requests and issues newest-first. The fake defaults to the order
    # it was given so existing tests keep their intent; set this to reproduce the real ordering,
    # which is what makes a resume watermark's direction matter (REPO-05).
    newest_first: bool = False

    calls: list[str] = field(default_factory=list)
    _pages_served: int = 0

    # ---------------------------------------------------------------- webhooks

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        """Same shape as the real thing: a bad signature yields nothing at all."""
        signature = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
        expected = (
            "sha256=" + hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        )
        if signature is None or not hmac.compare_digest(signature, expected):
            return None

        delivery_id = headers.get("X-GitHub-Delivery") or headers.get("x-github-delivery")
        if not delivery_id:
            return None
        payload: dict[str, Any] = json.loads(body)
        return WebhookEvent(
            provider=self.provider,
            delivery_id=delivery_id,
            event=headers.get("X-GitHub-Event", "push"),
            external_repo_id=str(payload.get("repository", {}).get("id", "")),
            payload=payload,
        )

    def sign(self, body: bytes) -> str:
        """Helper for callers that need a valid signature."""
        return "sha256=" + hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()

    # ---------------------------------------------------------------- reads

    async def repo_visibility(self, repo: RepoRef) -> Visibility:
        self._guard("repo_visibility")
        return self.visibility

    async def list_commits(
        self, repo: RepoRef, since: datetime | None, cursor: str | None
    ) -> Page[CommitMeta]:
        self._guard("list_commits")
        selected = [c for c in self.commits if since is None or c.committed_at > since]
        return self._paginate(self._ordered(selected, lambda c: c.committed_at), cursor)

    async def get_commit_diff(self, repo: RepoRef, sha: str, max_bytes: int) -> DiffResult:
        self._guard("get_commit_diff")
        text = self.diffs.get(sha, "")
        if len(text.encode()) > max_bytes:
            return DiffResult(
                sha=sha, text=text.encode()[:max_bytes].decode(errors="ignore"), truncated=True
            )
        return DiffResult(sha=sha, text=text)

    async def list_pull_requests(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[PullRequest]:
        self._guard("list_pull_requests")
        selected = [
            pr
            for pr in self.pull_requests
            if updated_since is None or pr.updated_at > updated_since
        ]
        return self._paginate(self._ordered(selected, lambda pr: pr.updated_at), cursor)

    async def list_reviews(self, repo: RepoRef, pr_number: int) -> list[Review]:
        self._guard("list_reviews")
        return list(self.reviews.get(pr_number, []))

    async def list_issues(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[Issue]:
        self._guard("list_issues")
        selected = [
            issue
            for issue in self.issues
            if updated_since is None or issue.updated_at > updated_since
        ]
        return self._paginate(self._ordered(selected, lambda issue: issue.updated_at), cursor)

    async def list_check_runs(self, repo: RepoRef, sha: str) -> list[CheckSummary]:
        self._guard("list_check_runs")
        return list(self.check_runs.get(sha, []))

    # ---------------------------------------------------------------- internals

    def _guard(self, call: str) -> None:
        self.calls.append(call)
        if isinstance(self.fail_with, AuthorizationError):
            raise self.fail_with
        if self.fail_with is not None:
            raise self.fail_with

    def _ordered[T](self, items: list[T], moment: Callable[[T], datetime]) -> list[T]:
        return sorted(items, key=moment, reverse=True) if self.newest_first else items

    def _paginate[T](self, items: list[T], cursor: str | None) -> Page[T]:
        if (
            self.rate_limit_after_pages is not None
            and self._pages_served >= self.rate_limit_after_pages
        ):
            raise RateLimitedError("fake rate limit", retry_after_seconds=60)

        start = int(cursor) if cursor else 0
        window = items[start : start + self.page_size]
        self._pages_served += 1
        next_start = start + self.page_size
        return Page(items=window, cursor=str(next_start) if next_start < len(items) else None)
