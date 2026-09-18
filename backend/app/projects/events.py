"""Domain events emitted by projects.service (docs/repo_layout.md §3.2).

`MembershipStarted` is what reporting subscribes to in order to derive the week's obligation the
moment somebody joins a project, rather than leaving it until the nightly `ensure_periods` run.
projects cannot call reporting itself: reporting sits above it in the layer order, and a membership
is the input to an obligation rather than the other way round.

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
class MembershipStarted:
    """PROJ-02: somebody is now on a project, however they got there.

    Carries `origin` because it decides which weeks the membership owes (PROJ-07), and the
    subscriber must not have to read the row back to find out.
    """

    workspace_id: UUID
    membership_id: UUID
    project_id: UUID
    student_id: UUID
    origin: str


def subscribe(event_type: type[Any], handler: Handler) -> Handler:
    """Idempotent: registering the same handler twice still delivers the event once."""
    handlers = _subscribers.setdefault(event_type, [])
    if handler not in handlers:
        handlers.append(handler)
    return handler


async def emit(event: Any, session: AsyncSession) -> None:
    for handler in _subscribers.get(type(event), []):
        await handler(event, session)
