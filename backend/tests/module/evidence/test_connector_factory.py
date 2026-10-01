"""Choosing a connector for a repository (REPO-01, architecture §8.1).

The worker syncs on a schedule, so something has to decide which connector a stored repository
gets without a person present. Two properties matter: a deployment with no GitHub App configured
must still run — on the fake connector, which is what the pilot and the demo use — and it must say
so, because silently syncing nothing looks exactly like a repository with no activity (AC-04).

Webhook verification is the exception to that fallback, and has its own factory function for it:
the in-memory connector's secret is a published constant, so a configured deployment that reached
it would reject every genuine delivery and accept forged ones.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.evidence.connectors import factory
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.evidence.connectors.github import GitHubConnector

pytestmark = pytest.mark.unit


def _settings(*, env: str = "test", **overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "github_app_id": "",
        "github_app_private_key_path": "",
        "github_webhook_secret": SecretStr(""),
    }
    base.update(overrides)
    # The environment is swapped in afterwards: a prod Settings validates the whole deployment
    # (database, object store, mail), which is not what these tests are about.
    return Settings(**base).model_copy(update={"env": env})  # type: ignore[arg-type]


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


# ------------------------------------------------- production never syncs from the test double


async def _refuses_to_read(connector: object) -> None:
    from app.evidence.connectors.base import AuthorizationError, RepoRef

    ref = RepoRef(provider="github", external_id="42", full_name="lab/baseline")
    with pytest.raises(AuthorizationError):
        await connector.list_commits(ref, None, None)  # type: ignore[attr-defined]
    with pytest.raises(AuthorizationError):
        await connector.repo_visibility(ref)  # type: ignore[attr-defined]


async def test_in_production_an_unconfigured_app_fails_the_sync_rather_than_syncing() -> None:
    """AC-04: an empty fake reads as a repository where nobody worked. In production the run has to
    end failed, which the overview shows as stale evidence."""
    connector = factory.build("github", credential_ref="123", settings=_settings(env="prod"))

    assert not isinstance(connector, FakeRepositoryConnector)
    await _refuses_to_read(connector)


async def test_in_production_a_repository_without_an_installation_fails_its_sync(tmp_path) -> None:
    key_file = tmp_path / "app.pem"
    key_file.write_text("key")
    connector = factory.build(
        "github",
        credential_ref=None,
        settings=_settings(
            env="prod",
            github_app_id="12345",
            github_app_private_key_path=str(key_file),
            github_webhook_secret=SecretStr("hook"),
        ),
    )

    assert not isinstance(connector, FakeRepositoryConnector)
    await _refuses_to_read(connector)


async def test_in_production_an_unreadable_key_fails_the_sync(tmp_path) -> None:
    settings = _settings(
        env="prod",
        github_app_id="12345",
        github_app_private_key_path=str(tmp_path / "missing.pem"),
        github_webhook_secret=SecretStr("hook"),
    )
    # The path is checked by `is_configured` too, so an unreadable key is "not configured" here.
    connector = factory.build("github", credential_ref="998877", settings=settings)

    assert not isinstance(connector, FakeRepositoryConnector)
    await _refuses_to_read(connector)


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


# ---------------------------------------------------------------- webhook verification


def _signed(secret: str, payload: dict[str, object]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "X-GitHub-Delivery": "d1",
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": signature,
    }


def test_a_configured_webhook_secret_is_verified_against_the_real_connector() -> None:
    settings = _settings(github_webhook_secret=SecretStr("the-real-secret"))
    verifier = factory.webhook_verifier("github", settings)

    assert isinstance(verifier, GitHubConnector)

    body, headers = _signed("the-real-secret", {"repository": {"id": 7}})
    event = verifier.verify_webhook(headers, body)
    assert event is not None
    assert event.external_repo_id == "7"


def test_the_test_doubles_published_secret_does_not_verify_a_configured_deployment() -> None:
    """The regression: the route built with no `credential_ref`, so it got the fake connector."""
    settings = _settings(github_webhook_secret=SecretStr("the-real-secret"))
    verifier = factory.webhook_verifier("github", settings)
    assert verifier is not None

    body, headers = _signed(FakeRepositoryConnector().webhook_secret, {"repository": {"id": 7}})
    assert verifier.verify_webhook(headers, body) is None


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_an_unconfigured_deployment_refuses_deliveries_rather_than_trust_the_fake(env: str) -> None:
    """The test double's secret is a published constant: verifying with it would let anyone forge
    a delivery and enqueue a sync. With no secret configured nothing can be verified, so the route
    answers 503 — in every environment, because a dev host can set a secret as easily as a test."""
    assert factory.webhook_verifier("github", _settings(env=env)) is None


def test_the_published_fake_secret_never_verifies_an_unconfigured_deployment() -> None:
    body, headers = _signed(FakeRepositoryConnector().webhook_secret, {"repository": {"id": 7}})
    verifier = factory.webhook_verifier("github", _settings(env="prod"))

    assert verifier is None or verifier.verify_webhook(headers, body) is None


def test_a_configured_app_without_a_webhook_secret_refuses_rather_than_falls_back(tmp_path) -> None:
    """Verifying against an empty secret would accept anything signed with an empty key."""
    key_file = tmp_path / "app.pem"
    key_file.write_text("-----BEGIN PRIVATE KEY-----\n")
    settings = _settings(
        github_app_id="123",
        github_app_private_key_path=str(key_file),
        github_webhook_secret=SecretStr(""),
    )

    assert factory.is_configured("github", settings) is True
    assert factory.webhook_verifier("github", settings) is None
