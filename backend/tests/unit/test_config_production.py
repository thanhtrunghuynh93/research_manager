"""`RM_ENV=prod` refuses to start on the development defaults (production-readiness.md §2.3).

The audit's point was that correctness depended on an operator reading a checklist: the deploy
runbook listed the variables that must be non-empty, and nothing enforced it. Every case here is
one line of that checklist turned into an assertion.

`model_copy` is deliberately not used — it skips validation, which is the whole subject.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.core.config import Settings

# A configuration that should start: nothing here is a value shipped in .env.example.
PRODUCTION = {
    "env": "prod",
    "public_url": "https://rm.example.org",
    "database_url": "postgresql+psycopg://rm:a-real-password@postgres:5432/rm",
    "s3_endpoint": "http://minio:9000",
    "s3_public_endpoint": "https://objects.rm.example.org",
    "s3_access_key": "a-real-key",
    "s3_secret_key": SecretStr("a-real-secret"),
    "metrics_token": SecretStr("a-real-token"),
    "smtp_host": "smtp.example.org",
    "mail_from": "supervision@rm.example.org",
}


def test_a_complete_production_configuration_starts() -> None:
    settings = Settings(**PRODUCTION)  # type: ignore[arg-type]
    assert settings.env == "prod"


def test_development_defaults_are_untouched_outside_production() -> None:
    """`make dev` must keep working on a clean checkout; that is what the defaults are for."""
    settings = Settings(env="dev")
    assert settings.smtp_host == "localhost"


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        (
            {"database_url": "postgresql+psycopg://rm:rm-dev-password@postgres:5432/rm"},
            "development password",
        ),
        (
            {"database_url": "postgresql+psycopg://rm:real@localhost:5432/rm"},
            "localhost",
        ),
        ({"s3_secret_key": SecretStr("rm-minio-dev-password")}, "development MinIO password"),
        ({"s3_access_key": ""}, "must both be set"),
        ({"s3_public_endpoint": "http://localhost:9000"}, "browser"),
        ({"public_url": "http://localhost:8020"}, "invitation-only"),
        ({"public_url": "http://rm.example.org"}, "must be https"),
        ({"metrics_token": SecretStr("")}, "refuse everybody"),
        ({"mail_from": "research-management@example.edu"}, "RM_MAIL_FROM is still"),
        ({"smtp_host": "mailpit"}, "ever receive an invitation"),
        ({"smtp_host": "localhost"}, "ever receive an invitation"),
        ({"github_app_id": "12345"}, "webhook endpoint returns 503"),
    ],
)
def test_each_development_default_refuses_to_start(
    override: dict[str, object], expected: str
) -> None:
    with pytest.raises(ValueError, match=expected):
        Settings(**{**PRODUCTION, **override})  # type: ignore[arg-type]


def test_every_violation_is_reported_at_once() -> None:
    """One at a time would turn a single edit of infra/.env into a deploy loop."""
    with pytest.raises(ValueError) as raised:
        Settings(
            **{
                **PRODUCTION,
                "public_url": "http://localhost:8020",
                "smtp_host": "mailpit",
                "metrics_token": SecretStr(""),
            }  # type: ignore[arg-type]
        )

    message = str(raised.value)
    assert "RM_PUBLIC_URL" in message
    assert "RM_SMTP_HOST" in message
    assert "RM_METRICS_TOKEN" in message


def test_a_configured_github_app_with_a_webhook_secret_is_accepted() -> None:
    settings = Settings(
        **{
            **PRODUCTION,
            "github_app_id": "12345",
            "github_webhook_secret": SecretStr("a-real-hmac-key"),
        }  # type: ignore[arg-type]
    )
    assert settings.github_app_id == "12345"
