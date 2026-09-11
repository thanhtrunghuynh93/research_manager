"""Alembic environment: async engine, metadata from app.core.db, URL from settings."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.core.audit  # noqa: F401  (every module with ORM models is imported for autogenerate)
import app.evidence.models  # noqa: F401
import app.identity.models  # noqa: F401
import app.notifications.models  # noqa: F401
import app.projects.models  # noqa: F401
import app.reporting.models  # noqa: F401
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Prefer the live environment over any cached Settings so tests and CI can point at their DB.
config.set_main_option(
    "sqlalchemy.url", os.environ.get("RM_DATABASE_URL") or get_settings().database_url
)
target_metadata = Base.metadata


def include_object(
    _object: object, name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    """The job queue's tables belong to procrastinate, so autogenerate leaves them alone."""
    return not (type_ == "table" and name is not None and name.startswith("procrastinate_"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
