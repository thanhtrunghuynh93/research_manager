"""procrastinate application, job-key helpers, and retry policy (architecture §12).

Two things about enqueueing that the code has to get right, because getting either wrong is
invisible until production:

*The app must be open before anything defers.* `defer_async` needs a connection, and procrastinate
raises `AppNotOpen` rather than opening one on demand. The worker opens it inside `run_worker`;
the API process has to open it in its lifespan, or every defer fails. `app.main` does that.

*A defer is not part of the caller's transaction.* `PsycopgConnector` takes its own connection
from its own pool, so an `INSERT` into `procrastinate_jobs` commits independently of the session
that asked for it. Deferring inline would therefore let a worker dequeue a job for a report
version that has not committed yet, and would leave an orphan job behind a rolled-back request.
So callers use `defer_after_commit`, which records the intent on the session; `flush_deferred`
sends it once the transaction has committed. `app.core.db.get_session` and `run_in_session` call
that, so a request handler only has to record the intent.

Use `queueing_lock=key(...)` on every defer so a second queued job with the same key is refused.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import procrastinate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)

# Modules list their tasks module here; app.worker imports them at startup so the tasks register.
TASK_MODULES: list[str] = [
    "app.tasks",
    "app.notifications.scheduler_tasks",
    "app.assessment.tasks",
    "app.evidence.tasks",
    "app.reporting.tasks",
]

RETRY_TRANSIENT = procrastinate.RetryStrategy(max_attempts=5, wait=10, exponential_wait=2)
RETRY_NONE = None

# Where pending defers live between the record and the flush. On `Session.info`, so it travels
# with the transaction rather than with a request or a task.
PENDING_DEFERS = "rm_pending_defers"


def key(domain: str, *parts: object) -> str:
    """Build a stable job key such as  assess:<student>:<project>:<period>:<version>:rate_rubric"""
    return ":".join([domain, *(str(p) for p in parts)])


def connector_for(settings: Settings | None = None) -> procrastinate.PsycopgConnector:
    """A connector against `settings`' database.

    The conninfo is fixed when the connector is constructed, so a process that resolves its
    settings after import (`create_app(settings)`) has to build its own rather than reuse the
    module-level one.
    """
    return procrastinate.PsycopgConnector(conninfo=(settings or get_settings()).libpq_dsn)


procrastinate_app = procrastinate.App(connector=connector_for(), import_paths=TASK_MODULES)


def defer_after_commit(
    session: AsyncSession,
    task: Any,
    *,
    queueing_lock: str | None = None,
    **kwargs: object,
) -> None:
    """Record a defer to be sent once this session's transaction commits.

    Nothing is enqueued here, so a handler that raises after calling this leaves no job behind.
    """
    pending: list[Callable[[], Awaitable[None]]] = session.info.setdefault(PENDING_DEFERS, [])

    async def _send() -> None:
        configured = task.configure(queueing_lock=queueing_lock) if queueing_lock else task
        await configured.defer_async(**kwargs)

    pending.append(_send)


async def flush_deferred(session: AsyncSession) -> int:
    """Send everything `defer_after_commit` recorded. Returns how many were sent.

    A defer that fails is logged and dropped rather than raised: by the time this runs the
    caller's work is committed, and losing the response to a queue that is briefly unreachable
    would turn a recoverable missing job into a failed request (requirements §10, AC-13).
    """
    pending: list[Callable[[], Awaitable[None]]] = session.info.pop(PENDING_DEFERS, [])
    sent = 0
    for send in pending:
        try:
            await send()
        except Exception:  # noqa: BLE001 - the committed work is what must survive
            log.exception("could not enqueue a job; the work it follows is recorded")
        else:
            sent += 1
    return sent


def discard_deferred(session: AsyncSession) -> None:
    """Drop pending defers, for a transaction that rolled back."""
    session.info.pop(PENDING_DEFERS, None)
