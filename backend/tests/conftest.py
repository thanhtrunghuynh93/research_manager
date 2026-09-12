"""Shared fixtures.

Database: set RM_TEST_DATABASE_URL to reuse a running Postgres (pgvector required); otherwise a
pgvector/pgvector:pg16 container is started once per session via testcontainers.

Each test runs inside a connection-level transaction that is rolled back afterwards, so services
may commit freely (`join_transaction_mode="create_savepoint"`) without leaking rows between tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.authz import Scope
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, get_session, init_engine
from app.core.types import Role
from app.identity import models, service
from app.main import create_app

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[object | None]:
    """The container running the test database, or None when an external one is configured.

    Exposed because the restore drill (AC-16) needs `pg_dump` and `pg_restore`, which live in the
    server image rather than on this machine.
    """
    if os.environ.get("RM_TEST_DATABASE_URL"):
        yield None
        return
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # older testcontainers
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        yield pg


@pytest.fixture(scope="session")
def database_url(postgres_container: object | None) -> str:
    external = os.environ.get("RM_TEST_DATABASE_URL")
    if external:
        return external
    assert postgres_container is not None
    return postgres_container.get_connection_url()  # type: ignore[attr-defined]


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


@pytest.fixture(scope="session")
async def engine(settings: Settings, migrated: None) -> AsyncIterator[AsyncEngine]:
    yield init_engine(settings)
    await dispose_engine()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """One session per test on its own connection; everything it wrote is rolled back after."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
async def client(settings: Settings, db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """HTTP client whose requests run in the test's transaction."""
    app = create_app(settings)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        try:
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    app.dependency_overrides[get_session] = _session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


# --------------------------------------------------------------------- identity fixtures


@pytest.fixture
async def workspace(db: AsyncSession) -> models.Workspace:
    from tests.factories import make_workspace

    return await make_workspace(db)


@pytest.fixture
async def prof(db: AsyncSession, workspace: models.Workspace) -> models.User:
    from tests.factories import make_user

    return await make_user(db, workspace, role=Role.PROF, email="prof@example.edu")


@pytest.fixture
async def student_a(db: AsyncSession, workspace: models.Workspace) -> models.User:
    from tests.factories import make_user

    return await make_user(db, workspace, role=Role.STUDENT, email="student-a@example.edu")


@pytest.fixture
async def student_b(db: AsyncSession, workspace: models.Workspace) -> models.User:
    from tests.factories import make_user

    return await make_user(db, workspace, role=Role.STUDENT, email="student-b@example.edu")


@pytest.fixture
async def prof_scope(db: AsyncSession, prof: models.User) -> Scope:
    return await service.scope_for(db, prof)


@pytest.fixture
async def student_a_scope(db: AsyncSession, student_a: models.User) -> Scope:
    return await service.scope_for(db, student_a)


@pytest.fixture
async def student_b_scope(db: AsyncSession, student_b: models.User) -> Scope:
    return await service.scope_for(db, student_b)
