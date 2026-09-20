"""The worker has to import whatever registers a domain-event subscriber.

Reading an attachment moved into a job, and reading announces `ArtifactExtracted`, which evidence
turns into index entries. Every `tasks.py` imports its service lazily inside the job, so the
subscriber modules are not imported by the task list alone — and an emit with nothing subscribed
does not raise. The job succeeds, the log says the file was read, and nothing is indexed. That
happened on the live stack, and this is the check that would have caught it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.jobs import SUBSCRIBER_MODULES

pytestmark = pytest.mark.unit

APP = Path(__file__).resolve().parents[2] / "app"
REGISTERS = re.compile(r"^register_subscriptions\(\)$", re.MULTILINE)


def test_every_module_that_registers_subscribers_is_imported_by_the_worker() -> None:
    registering = {
        "app." + str(path.relative_to(APP).with_suffix("")).replace("/", ".")
        for path in APP.rglob("*.py")
        if REGISTERS.search(path.read_text())
    }

    assert registering, "the scan found nothing, so it is checking nothing"
    assert registering == set(SUBSCRIBER_MODULES)


def test_the_worker_imports_both_lists() -> None:
    from app import worker
    from app.core.jobs import TASK_MODULES

    source = Path(worker.__file__).read_text()
    assert "TASK_MODULES" in source and "SUBSCRIBER_MODULES" in source
    assert TASK_MODULES, "task modules are what the worker runs at all"
