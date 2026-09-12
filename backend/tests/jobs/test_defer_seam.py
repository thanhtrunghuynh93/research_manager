"""The seam between "a handler asked for a job" and "the queue has one" (architecture §12).

Every other job test stubs `defer_pipeline` or calls the pipeline directly, which is right for
testing what gets asked for but leaves the wiring itself unexercised. These tests are about the
wiring: that the API process can defer at all, and that nothing is enqueued for a transaction
that did not commit.

The two defects this covers shipped together and were invisible from the rest of the suite. The
API process never opened the procrastinate app, so every `defer_async` raised `AppNotOpen` and a
submitted report enqueued nothing; and the defer ran inline, so a worker could dequeue a job for
a report version that had not committed.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import jobs
from app.core.config import Settings

pytestmark = pytest.mark.module


class _Recorder:
    """Stands in for a procrastinate task: records that it was asked, and when."""

    def __init__(self, sent: list[dict[str, Any]]) -> None:
        self.sent = sent
        self.lock: str | None = None

    def configure(self, *, queueing_lock: str | None = None) -> _Recorder:
        self.lock = queueing_lock
        return self

    async def defer_async(self, **kwargs: object) -> None:
        self.sent.append({"queueing_lock": self.lock, **kwargs})


async def test_nothing_is_enqueued_before_the_transaction_commits(db: AsyncSession) -> None:
    sent: list[dict[str, Any]] = []
    jobs.defer_after_commit(db, _Recorder(sent), queueing_lock="lock:1", subject="x")

    assert sent == []  # recorded only

    await db.commit()
    assert sent == []  # still nothing: the flush is what sends

    assert await jobs.flush_deferred(db) == 1
    assert sent == [{"queueing_lock": "lock:1", "subject": "x"}]


async def test_a_rolled_back_transaction_leaves_no_job(db: AsyncSession) -> None:
    """An orphan job would look for rows that never landed."""
    sent: list[dict[str, Any]] = []
    jobs.defer_after_commit(db, _Recorder(sent), queueing_lock="lock:2", subject="y")

    jobs.discard_deferred(db)
    await db.rollback()

    assert await jobs.flush_deferred(db) == 0
    assert sent == []


async def test_a_queue_that_refuses_does_not_lose_the_committed_work(db: AsyncSession) -> None:
    """The work is committed by then: a missing job is recoverable, a failed request is not."""

    class _Broken:
        def configure(self, **_: object) -> _Broken:
            return self

        async def defer_async(self, **_: object) -> None:
            raise RuntimeError("queue unreachable")

    jobs.defer_after_commit(db, _Broken(), queueing_lock="lock:3")
    assert await jobs.flush_deferred(db) == 0  # logged and dropped, not raised


async def test_flushing_twice_does_not_send_twice(db: AsyncSession) -> None:
    sent: list[dict[str, Any]] = []
    jobs.defer_after_commit(db, _Recorder(sent), queueing_lock="lock:4")

    await jobs.flush_deferred(db)
    await jobs.flush_deferred(db)

    assert len(sent) == 1


async def test_the_api_process_can_actually_defer(settings: Settings, engine: AsyncEngine) -> None:
    """The regression: `app.main`'s lifespan never opened the app, so every defer raised.

    This is the only test that opens the real connector. It commits outside the per-test
    transaction, so it cleans up the row it enqueues.
    """
    from app.tasks import queue_health

    connector = jobs.connector_for(settings)
    with jobs.procrastinate_app.replace_connector(connector):
        await jobs.procrastinate_app.open_async()
        try:
            await queue_health.configure(queueing_lock="test:defer-seam").defer_async(timestamp=0)
        finally:
            await jobs.procrastinate_app.close_async()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM procrastinate_jobs "
                    "WHERE queueing_lock = 'test:defer-seam'"
                )
            )
        ).scalar_one()
        await session.execute(
            text("DELETE FROM procrastinate_jobs WHERE queueing_lock = 'test:defer-seam'")
        )
        await session.commit()

    assert queued == 1
