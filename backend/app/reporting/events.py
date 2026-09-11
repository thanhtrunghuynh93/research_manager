"""Domain events emitted by reporting.service (docs/repo_layout.md §3.2).

`ReportSubmitted` is what the assessment module subscribes to in order to enqueue its pipeline,
which is how reporting stays unaware of assessment (architecture §4.1).

Handlers run inside the emitting transaction, which has flushed but not committed: write rows and
enqueue jobs, never call an external service directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

Handler = Callable[[Any], Awaitable[None]]
_subscribers: dict[type[Any], list[Handler]] = {}


@dataclass(frozen=True, slots=True)
class ReportSubmitted:
    workspace_id: UUID
    report_id: UUID
    report_version_id: UUID
    student_id: UUID
    period_id: UUID


def subscribe(event_type: type[Any], handler: Handler) -> Handler:
    _subscribers.setdefault(event_type, []).append(handler)
    return handler


async def emit(event: Any) -> None:
    for handler in _subscribers.get(type(event), []):
        await handler(event)
