"""Async SQLAlchemy engine, session factory, and the declarative base shared by all modules."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, MetaData, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import Settings, get_settings
from app.core.ids import uuid7

# Deterministic constraint names so migrations and docs agree (architecture §5.4).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        UUID: PG_UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings, **engine_kwargs: Any) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(settings.database_url, pool_pre_ping=True, **engine_kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("database engine not initialised; call init_engine() first")
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success, rolled back on error.

    Jobs recorded with `jobs.defer_after_commit` are sent here, after the commit, so a worker
    never dequeues a job for rows the request has not yet made visible (app.core.jobs).
    """
    from app.core import jobs

    async with session_factory()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            jobs.discard_deferred(session)
            await session.rollback()
            raise
        await jobs.flush_deferred(session)


def run_in_session[T](operation: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run one async operation in its own engine, session, and transaction.

    For operator commands (app/cli.py and each module's cli.py), which have no request lifespan.
    """

    async def _main() -> T:
        from app.core import jobs

        init_engine(get_settings())
        try:
            async with session_factory()() as session:
                result = await operation(session)
                await session.commit()
                await jobs.flush_deferred(session)
                return result
        finally:
            await dispose_engine()

    return asyncio.run(_main())


async def ping() -> bool:
    async with session_factory()() as session:
        result = await session.execute(text("SELECT 1"))
        return bool(result.scalar_one() == 1)
