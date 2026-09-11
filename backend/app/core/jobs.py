"""procrastinate application, job-key helpers, and retry policy (architecture §12).

Jobs are enqueued inside the caller's database transaction so a report and its pipeline jobs
persist together or not at all. Use `queueing_lock=key(...)` on every defer so a second queued
job with the same key is refused.
"""

from __future__ import annotations

import procrastinate

from app.core.config import get_settings

# Modules append their tasks module path here; app.worker imports them at startup.
TASK_MODULES: list[str] = []

RETRY_TRANSIENT = procrastinate.RetryStrategy(max_attempts=5, wait=10, exponential_wait=2)
RETRY_NONE = None


def key(domain: str, *parts: object) -> str:
    """Build a stable job key such as  assess:<student>:<project>:<period>:<version>:rate_rubric"""
    return ":".join([domain, *(str(p) for p in parts)])


def _connector() -> procrastinate.PsycopgConnector:
    return procrastinate.PsycopgConnector(conninfo=get_settings().libpq_dsn)


procrastinate_app = procrastinate.App(connector=_connector(), import_paths=TASK_MODULES)
