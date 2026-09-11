"""Shared fixtures.

Database: set RM_TEST_DATABASE_URL to reuse a running Postgres (pgvector required); otherwise a
pgvector/pgvector:pg16 container is started once per session via testcontainers.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, init_engine
from app.main import create_app

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("RM_TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # older testcontainers
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    # app.main primes the settings cache with defaults at import; point everything at the test DB.
    os.environ["RM_DATABASE_URL"] = database_url
    os.environ["RM_ENV"] = "test"
    get_settings.cache_clear()
    return Settings(env="test", database_url=database_url, secret_key="test-secret")  # type: ignore[arg-type]


@pytest.fixture(scope="session", autouse=True)
def migrated(settings: Settings) -> None:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    init_engine(settings)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await dispose_engine()
