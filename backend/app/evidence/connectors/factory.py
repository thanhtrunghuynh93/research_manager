"""Choosing a connector for a stored repository (REPO-01, architecture §8.1).

The worker syncs on a schedule, so something has to make this decision with no person present.

The fallback is deliberate and it is loud. A deployment with no GitHub App configured — a pilot, a
demo, an evaluation host — still runs, on the fake connector, and the log says which one it got.
Silently syncing nothing would be the worst outcome available: it looks exactly like a repository
where nobody worked, which is the inference AC-04 exists to prevent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.evidence.connectors.base import RepositoryConnector
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
        log.info("no %s app configured; using the in-memory connector", provider)
        return FakeRepositoryConnector()
    if not credential_ref:
        log.warning(
            "repository has no installation recorded; using the in-memory connector rather than "
            "reporting an empty history"
        )
        return FakeRepositoryConnector()

    try:
        private_key = Path(active.github_app_private_key_path).read_text(encoding="utf-8")
    except OSError as error:
        # A misconfigured path should surface as stale evidence on the dashboard, not a dead
        # worker that stops syncing every repository.
        log.error("could not read the GitHub App private key: %s", error)
        return FakeRepositoryConnector()

    return GitHubConnector(
        app_id=active.github_app_id,
        private_key=private_key,
        webhook_secret=active.github_webhook_secret.get_secret_value(),
        installation_id=credential_ref,
        client=client,
    )
