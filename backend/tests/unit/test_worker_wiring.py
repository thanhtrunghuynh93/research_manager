"""The worker must import whatever registers a job or an event subscriber, and open a session.

Reading an attachment moved into a job, and reading announces `ArtifactExtracted`, which evidence
turns into index entries. Every `tasks.py` imports its service lazily inside the job, so the
subscriber modules are not imported by the task list alone — and an emit with nothing subscribed
does not raise. The job succeeds, the log says the file was read, and nothing is indexed. That
happened on the live stack, and this is the check that would have caught it.

The API initialises the engine in its lifespan. The worker has no lifespan, so it does it itself —
without this, every periodic task fails on its first database call.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from pydantic import SecretStr

from app import worker
from app.core import db, storage
from app.core.config import Settings
from app.core.jobs import SUBSCRIBER_MODULES, TASK_MODULES, procrastinate_app

pytestmark = pytest.mark.unit

APP = Path(__file__).resolve().parents[2] / "app"
REGISTERS = re.compile(r"^register_subscriptions\(\)$", re.MULTILINE)
# Never connected to: creating an async engine opens nothing until a query runs.
UNREACHABLE = "postgresql+psycopg://worker:worker@127.0.0.1:1/worker"


def test_every_module_that_registers_subscribers_is_imported_by_the_worker() -> None:
    registering = {
        "app." + str(path.relative_to(APP).with_suffix("")).replace("/", ".")
        for path in APP.rglob("*.py")
        if REGISTERS.search(path.read_text())
    }

    assert registering, "the scan found nothing, so it is checking nothing"
    assert registering == set(SUBSCRIBER_MODULES)


def test_bootstrap_imports_both_lists_and_opens_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bootstrap replaces process globals; monkeypatch puts the test session's back afterwards.
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    monkeypatch.setattr(storage, "_store", storage._store)
    imported: list[str] = []
    real_import = importlib.import_module

    def _recording_import(name: str, package: str | None = None) -> object:
        imported.append(name)
        return real_import(name, package)

    monkeypatch.setattr(worker.importlib, "import_module", _recording_import)

    # No provider key and no bucket, whatever the environment says: the fakes stay installed.
    settings = Settings(
        env="test", database_url=UNREACHABLE, openai_api_key=SecretStr(""), s3_access_key=""
    )
    worker.bootstrap(settings)

    assert TASK_MODULES, "task modules are what the worker runs at all"
    assert set(TASK_MODULES) <= set(imported)
    assert set(SUBSCRIBER_MODULES) <= set(imported)
    assert db.session_factory() is not None


def test_every_task_module_registers_its_jobs() -> None:
    for module in TASK_MODULES:
        importlib.import_module(module)

    registered = {task.func.__module__ for task in procrastinate_app.tasks.values()}

    assert set(TASK_MODULES) <= registered, "a task module that registers nothing runs nothing"
