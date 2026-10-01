"""Choosing a connector for a stored repository (REPO-01, architecture §8.1).

The worker syncs on a schedule, so something has to make this decision with no person present.

Outside production the fallback is deliberate and loud: a dev or test deployment with no GitHub App
configured still runs, on the fake connector, and the log says which one it got. In production
there is no fallback. Syncing nothing from an empty test double would be the worst outcome
available — it looks exactly like a repository where nobody worked, which is the inference AC-04
exists to prevent — so an unconfigured production deployment gets a connector that refuses every
read, and the sync run ends `failed`, which the overview shows as stale evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.evidence.connectors.base import (
    AuthorizationError,
    CheckSummary,
    CommitMeta,
    DiffResult,
    Issue,
    Page,
    Provider,
    PullRequest,
    RepoRef,
    RepositoryConnector,
    Review,
    Visibility,
    WebhookEvent,
)
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.evidence.connectors.github import GitHubConnector

log = logging.getLogger(__name__)

PROVIDERS = frozenset({"github"})


def is_configured(provider: str, settings: Settings | None = None) -> bool:
    """True when this deployment has real credentials for the provider."""
    active = settings or get_settings()
    if provider != "github":
        return False
    return bool(active.github_app_id) and Path(active.github_app_private_key_path or "").is_file()


def webhook_verifier(provider: str, settings: Settings | None = None) -> RepositoryConnector | None:
    """The connector that checks a delivery signature — no installation involved.

    Verification needs only the shared webhook secret, so this must not go through `build`:
    `build` needs a `credential_ref` and falls back to the in-memory connector without one.

    Returns None whenever no webhook secret is set, and the route answers 503. Never the in-memory
    connector: its secret is a published constant, so verifying with it would let anyone forge a
    delivery and enqueue a sync. And never an empty secret, which would accept any delivery signed
    with an empty key. A dev host that wants webhooks sets a secret, as production does.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"no connector for provider {provider!r}")

    active = settings or get_settings()
    secret = active.github_webhook_secret.get_secret_value()
    if secret:
        return GitHubConnector(
            app_id=active.github_app_id,
            private_key="",  # reads are not reachable from this instance
            webhook_secret=secret,
            installation_id="",
        )
    log.error("no %s webhook secret is set; deliveries cannot be verified", provider)
    return None


class UnavailableConnector:
    """What production gets when it cannot reach the provider: every read refuses.

    `AuthorizationError` because a person has to fix the configuration and a retry cannot, which
    is exactly how the sync loop treats it — the run ends `failed` and the repository is marked
    unauthorized, rather than "completed, zero events" (REPO-05, AC-04).
    """

    def __init__(self, provider: Provider, reason: str) -> None:
        self.provider: Provider = provider
        self.reason = reason

    def _refuse(self) -> AuthorizationError:
        return AuthorizationError(self.reason)

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        return None

    async def repo_visibility(self, repo: RepoRef) -> Visibility:
        raise self._refuse()

    async def list_commits(
        self, repo: RepoRef, since: datetime | None, cursor: str | None
    ) -> Page[CommitMeta]:
        raise self._refuse()

    async def get_commit_diff(self, repo: RepoRef, sha: str, max_bytes: int) -> DiffResult:
        raise self._refuse()

    async def list_pull_requests(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[PullRequest]:
        raise self._refuse()

    async def list_reviews(self, repo: RepoRef, pr_number: int) -> list[Review]:
        raise self._refuse()

    async def list_issues(
        self, repo: RepoRef, updated_since: datetime | None, cursor: str | None
    ) -> Page[Issue]:
        raise self._refuse()

    async def list_check_runs(self, repo: RepoRef, sha: str) -> list[CheckSummary]:
        raise self._refuse()


def _fallback(provider: str, active: Settings, reason: str) -> RepositoryConnector:
    """The in-memory connector outside production; a refusing one in it."""
    if active.env == "prod":
        log.error("%s; the sync will fail until it is fixed", reason)
        return UnavailableConnector(provider, reason)  # type: ignore[arg-type]
    log.warning("%s; using the in-memory connector", reason)
    return FakeRepositoryConnector()


def build(
    provider: str,
    *,
    credential_ref: str | None,
    settings: Settings | None = None,
    client: Any = None,
) -> RepositoryConnector:
    """The connector for one repository.

    `credential_ref` holds the installation id the professor granted (architecture §8.1).

    GitHub App installation tokens are minted per run by the connector itself and never persisted,
    so what is stored here is only the installation the professor granted.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"no connector for provider {provider!r}")

    active = settings or get_settings()
    if not is_configured(provider, active):
        return _fallback(provider, active, f"no {provider} app is configured")
    if not credential_ref:
        return _fallback(provider, active, "the repository has no installation recorded")

    try:
        private_key = Path(active.github_app_private_key_path).read_text(encoding="utf-8")
    except OSError as error:
        # A misconfigured path should surface as stale evidence on the dashboard, not a dead
        # worker that stops syncing every repository.
        return _fallback(provider, active, f"could not read the GitHub App private key: {error}")

    return GitHubConnector(
        app_id=active.github_app_id,
        private_key=private_key,
        webhook_secret=active.github_webhook_secret.get_secret_value(),
        installation_id=credential_ref,
        client=client,
    )
