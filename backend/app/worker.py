"""Worker entry point: runs procrastinate jobs and periodic tasks.

Run:  python -m app.worker
Every module that defines jobs lists its tasks module in app.core.jobs.TASK_MODULES so the
worker imports them here (they register themselves with the procrastinate app on import).
"""

from __future__ import annotations

import importlib
import logging

from app.ai import bootstrap as ai_bootstrap
from app.core.config import Settings, get_settings
from app.core.db import init_engine
from app.core.jobs import TASK_MODULES, procrastinate_app

log = logging.getLogger(__name__)


def bootstrap(settings: Settings) -> None:
    """Import the task modules and open the database engine.

    The API does the second half in its lifespan; the worker has no lifespan, and its tasks call
    the same services, so it does it here.
    """
    for module in TASK_MODULES:
        importlib.import_module(module)
    init_engine(settings)
    # The worker makes every model call the pipeline needs, so it installs the provider too.
    ai_bootstrap.install(settings)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    bootstrap(settings)
    log.info("worker starting; task modules: %s", ", ".join(TASK_MODULES) or "(none yet)")
    procrastinate_app.run_worker(
        concurrency=settings.worker_concurrency, install_signal_handlers=True
    )


if __name__ == "__main__":
    main()
