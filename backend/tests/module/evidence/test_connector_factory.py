"""Choosing a connector for a repository (REPO-01, architecture §8.1).

The worker syncs on a schedule, so something has to decide which connector a stored repository
gets without a person present. Two properties matter: a deployment with no GitHub App configured
must still run — on the fake connector, which is what the pilot and the demo use — and it must say
so, because silently syncing nothing looks exactly like a repository with no activity (AC-04).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.evidence.connectors import factory
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.evidence.connectors.github import GitHubConnector

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "github_app_id": "",
        "github_app_private_key_path": "",
        "github_webhook_secret": SecretStr(""),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_without_a_configured_app_the_fake_connector_is_used() -> None:
    connector = factory.build("github", credential_ref="123", settings=_settings())

    assert isinstance(connector, FakeRepositoryConnector)


def test_with_a_configured_app_the_real_connector_is_built(tmp_path) -> None:
    key_file = tmp_path / "app.pem"
    key_file.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nnot-a-real-key\n-----END RSA PRIVATE KEY-----"
    )

    connector = factory.build(
        "github",
        credential_ref="998877",
        settings=_settings(
            github_app_id="12345",
            github_app_private_key_path=str(key_file),
            github_webhook_secret=SecretStr("hook"),
        ),
    )

    assert isinstance(connector, GitHubConnector)


def test_a_missing_key_file_falls_back_rather_than_crashing_the_worker(tmp_path) -> None:
    """A misconfigured path should surface as stale evidence on the dashboard, not a dead worker."""
    connector = factory.build(
        "github",
        credential_ref="998877",
        settings=_settings(
            github_app_id="12345",
            github_app_private_key_path=str(tmp_path / "missing.pem"),
            github_webhook_secret=SecretStr("hook"),
        ),
    )

    assert isinstance(connector, FakeRepositoryConnector)


def test_a_repository_with_no_installation_recorded_gets_the_fake(tmp_path) -> None:
    key_file = tmp_path / "app.pem"
    key_file.write_text("key")

    connector = factory.build(
        "github",
        credential_ref=None,
        settings=_settings(
            github_app_id="12345",
            github_app_private_key_path=str(key_file),
            github_webhook_secret=SecretStr("hook"),
        ),
    )

    assert isinstance(connector, FakeRepositoryConnector)


def test_an_unknown_provider_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="gitlab"):
        factory.build("gitlab", credential_ref="1", settings=_settings())


def test_the_factory_reports_whether_a_provider_is_actually_configured() -> None:
    assert factory.is_configured("github", _settings()) is False
    assert (
        factory.is_configured(
            "github",
            _settings(github_app_id="1", github_app_private_key_path=__file__),
        )
        is True
    )
