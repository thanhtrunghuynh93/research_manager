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

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[Any, "AsyncSession"], Awaitable[None]]
_subscribers: dict[type[Any], list[Handler]] = {}


@dataclass(frozen=True, slots=True)
class ReportSubmitted:
    workspace_id: UUID
    report_id: UUID
    report_version_id: UUID
    student_id: UUID
    period_id: UUID
    resubmitted: bool


@dataclass(frozen=True, slots=True)
class ArtifactExtracted:
    """REP-04: an attachment became readable text, and is now citable evidence.

    Carries the text rather than an id to fetch, because the handler runs inside the emitting
    transaction and the extraction has already been done once.
    """

    workspace_id: UUID
    artifact_id: UUID
    version_id: UUID
    version_no: int
    project_id: UUID | None
    owner_student_id: UUID
    supported_claim: str
    text: str
    source_time: Any


@dataclass(frozen=True, slots=True)
class ArtifactRemoved:
    """REP-04: an attachment the student took back before the week was submitted.

    Carries every version id rather than the artifact's, because evidence is indexed per version:
    a figure replaced twice has three references, and forgetting one of them would leave the
    others answerable in search (requirements §11, "propagate authorized deletion to file storage,
    searchable indexes, answer caches").
    """

    workspace_id: UUID
    artifact_id: UUID
    version_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RevisionRequested:
    """REP-05: one request, about one project entry. A week can hold several.

    `request_id` identifies this request rather than the report, so a second request in the same
    week is a second thing to tell the student about and a redelivered job is still one.
    """

    workspace_id: UUID
    report_id: UUID
    request_id: UUID
    period_id: UUID
    student_id: UUID
    project_id: UUID | None
    reason: str


def subscribe(event_type: type[Any], handler: Handler) -> Handler:
    """Idempotent: registering the same handler twice still delivers the event once."""
    handlers = _subscribers.setdefault(event_type, [])
    if handler not in handlers:
        handlers.append(handler)
    return handler


async def emit(event: Any, session: AsyncSession) -> None:
    for handler in _subscribers.get(type(event), []):
        await handler(event, session)
