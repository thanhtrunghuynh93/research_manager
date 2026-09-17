"""Application settings. Every environment variable is documented in docs/repo_layout.md §3.6."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MASKED_VALUE = "***"

# The development defaults from .env.example, by the name an operator would see them under. Each
# one exists so `make dev` works on a clean checkout; each one surviving into production is a
# different silent failure, so `prod` refuses to start on any of them rather than trusting a
# checklist to have been read (docs/runbooks/production-readiness.md §2.3).
_DEV_PASSWORDS = ("rm-dev-password", "rm-minio-dev-password")
_DEV_MAIL_FROM = "research-management@example.edu"
_DEV_SMTP_HOSTS = ("mailpit", "localhost")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RM_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    public_url: str = "http://localhost:8020"

    # The host-side default, for the make targets that run alembic and the seed outside the
    # containers. It has to match what the dev stack actually creates: the credential from
    # .env.example, on the port infra/docker-compose.dev.yml publishes. Inside the containers
    # RM_DATABASE_URL names `postgres:5432` on the compose network instead.
    database_url: str = "postgresql+psycopg://rm:rm-dev-password@localhost:8022/rm"

    s3_endpoint: str = "http://localhost:9000"
    # Where the *browser* reaches object storage. The application and the browser do not share a
    # network: inside compose the store is `minio:9000`, which no browser can resolve, and a
    # presigned URL built for that host is unusable the moment it leaves the container. Empty
    # means the two are the same host, which is true outside compose and in production behind one
    # origin. It cannot be derived by rewriting the URL: SigV4 signs the Host header.
    s3_public_endpoint: str = ""
    s3_bucket: str = "rm-dev"
    s3_access_key: str = ""
    s3_secret_key: SecretStr = SecretStr("")

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1"
    openai_embed_model: str = "text-embedding-3-small"

    github_app_id: str = ""
    github_app_private_key_path: str = ""
    github_webhook_secret: SecretStr = SecretStr("")

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    mail_from: str = "research-management@example.edu"

    # Who may read /metrics. Prometheus scrapes it, people should not: the gauges name every
    # workspace's queue depth and sync staleness, and `?fresh=1` turns a scrape into database
    # work. Required in prod; without one there, the endpoint refuses everybody.
    metrics_token: SecretStr = SecretStr("")

    upload_max_file_mb: int = Field(default=25, ge=1)
    worker_concurrency: int = Field(default=4, ge=1)

    # How many sign-in attempts one address may make in five minutes. The default is the
    # production limit and nothing in a deployment should raise it; it is a setting only so that
    # the end-to-end suite, which signs in as several people from one address, is not throttled by
    # the defence it is not testing. The dev compose file raises it, prod never sets it.
    auth_login_attempts: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def _refuse_development_defaults_in_production(self) -> Settings:
        """Refuse to start a production deployment that is still wearing its development clothes.

        Every check below is one the deploy runbook used to ask an operator to make by eye, and
        each failure mode is quiet rather than loud: a shipped database password is a credential
        that is published in this repository, `mailpit` accepts every message and delivers none,
        and a localhost public URL produces invitation links that open on nobody's machine.

        All violations are collected and reported together. Finding the next one only after
        fixing this one turns a single edit of `infra/.env` into a deploy loop.
        """
        if self.env != "prod":
            return self

        bad: list[str] = []

        if any(password in self.database_url for password in _DEV_PASSWORDS):
            bad.append("RM_DATABASE_URL still carries the development password from .env.example")
        if "localhost" in self.database_url:
            bad.append("RM_DATABASE_URL points at localhost, not the compose `postgres` host")

        if self.s3_secret_key.get_secret_value() in _DEV_PASSWORDS:
            bad.append("RM_S3_SECRET_KEY is the development MinIO password")
        if not self.s3_access_key or not self.s3_secret_key.get_secret_value():
            bad.append("RM_S3_ACCESS_KEY and RM_S3_SECRET_KEY must both be set")
        if "localhost" in self.s3_public_endpoint:
            bad.append(
                "RM_S3_PUBLIC_ENDPOINT points at localhost; it is the address a *browser* uses "
                "to upload an attachment, so it must be the public https://objects.<domain>"
            )

        if "localhost" in self.public_url:
            bad.append(
                "RM_PUBLIC_URL points at localhost; every invitation and recovery link is built "
                "from it, and enrolment is invitation-only"
            )
        if self.public_url.startswith("http://"):
            bad.append("RM_PUBLIC_URL must be https in production; the session cookie is Secure")

        if not self.metrics_token.get_secret_value():
            bad.append("RM_METRICS_TOKEN is empty, which makes /api/metrics refuse everybody")

        # Empty is checked separately from the development values, and neither is the other's
        # special case: `mailpit` sends nothing while looking configured, and empty is a relay
        # nobody has chosen yet. Both end with a student who was never contacted, and an earlier
        # version of this validator let empty through because it only compared against the
        # shipped defaults.
        if not self.mail_from:
            bad.append("RM_MAIL_FROM is empty")
        elif self.mail_from == _DEV_MAIL_FROM:
            bad.append(f"RM_MAIL_FROM is still {_DEV_MAIL_FROM}")
        if not self.smtp_host:
            bad.append("RM_SMTP_HOST is empty; no invitation or recovery email can be sent")
        elif self.smtp_host in _DEV_SMTP_HOSTS:
            bad.append(
                f"RM_SMTP_HOST is {self.smtp_host}, which accepts every message and delivers "
                "none; no student would ever receive an invitation"
            )

        if self.github_app_id and not self.github_webhook_secret.get_secret_value():
            bad.append(
                "RM_GITHUB_APP_ID is set without RM_GITHUB_WEBHOOK_SECRET, so the webhook "
                "endpoint returns 503 and pushes never trigger a sync"
            )

        if bad:
            raise ValueError(
                "RM_ENV=prod with development configuration still in place:\n"
                + "\n".join(f"  - {item}" for item in bad)
            )
        return self

    @property
    def libpq_dsn(self) -> str:
        """The SQLAlchemy URL as a plain libpq DSN (procrastinate and psycopg want this form)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def masked(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, value in self.model_dump().items():
            out[f"RM_{name.upper()}"] = _MASKED_VALUE if isinstance(value, SecretStr) else value
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
