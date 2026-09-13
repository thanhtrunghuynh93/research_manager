"""Application settings. Every environment variable is documented in docs/repo_layout.md §3.6."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_MASKED_VALUE = "***"


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
    secret_key: SecretStr = SecretStr("dev-only-change-me")

    s3_endpoint: str = "http://localhost:9000"
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
