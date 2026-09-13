"""The worker must be able to open a session: its tasks are the same services the API calls.

The API initialises the engine in its lifespan. The worker has no lifespan, so it does it itself —
without this, every periodic task fails on its first database call.
"""

from __future__ import annotations

import pytest

from app.core import db
from app.core.config import Settings
from app.core.jobs import TASK_MODULES
from app.worker import bootstrap


@pytest.mark.unit
def test_bootstrap_initialises_the_engine_and_imports_the_tasks(settings: Settings) -> None:
    bootstrap(settings)

    assert db.session_factory() is not None
    assert TASK_MODULES, "a worker with no task modules would sit idle"


@pytest.mark.unit
def test_every_task_module_imports(settings: Settings) -> None:
    import importlib

    for module in TASK_MODULES:
        assert importlib.import_module(module) is not None
