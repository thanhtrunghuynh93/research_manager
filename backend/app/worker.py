"""Worker entry point: runs procrastinate jobs and periodic tasks.

Run:  python -m app.worker
Every module that defines jobs lists its tasks module in app.core.jobs.TASK_MODULES so the
worker imports them here (they register themselves with the procrastinate app on import).
"""

from __future__ import annotations

import importlib
import logging

from app.core.config import get_settings
from app.core.jobs import TASK_MODULES, procrastinate_app

log = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    for module in TASK_MODULES:
        importlib.import_module(module)
    log.info("worker starting; task modules: %s", ", ".join(TASK_MODULES) or "(none yet)")
    procrastinate_app.run_worker(
        concurrency=settings.worker_concurrency, install_signal_handlers=True
    )


if __name__ == "__main__":
    main()
