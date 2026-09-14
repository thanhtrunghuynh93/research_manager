"""Domain events emitted by identity.service (docs/repo_layout.md §3.2).

Handlers are registered by the modules that react, which keeps identity unaware of them:
notifications subscribes to the two token events and sends the invitation and recovery emails
(AUTH-01), and projects subscribes to `UserRemoved` and ends the memberships (ADR 0011).

The plaintext token travels in the event and never in an API response: only the addressee of the
email may learn it.

Handlers run inside the emitting transaction, which has flushed but not committed. A handler must
therefore only write rows and enqueue jobs — never talk to a mail provider directly — so a later
rollback cannot leave an email announcing an invitation that does not exist (architecture §12).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

Handler = Callable[[Any, "AsyncSession"], Awaitable[None]]
_subscribers: dict[type[Any], list[Handler]] = {}


@dataclass(frozen=True, slots=True)
class InvitationCreated:
    workspace_id: UUID
    user_id: UUID
    email: str
    display_name: str
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordResetRequested:
    workspace_id: UUID
    user_id: UUID
    email: str
    display_name: str
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UserDeactivated:
    workspace_id: UUID
    user_id: UUID
    actor_id: UUID | None


@dataclass(frozen=True, slots=True)
class UserRemoved:
    """A student taken off the roll, not merely suspended (ADR 0011).

    projects subscribes and ends every active membership at `at`, which is what stops the weekly
    obligations. identity cannot call projects itself: it sits below it in the layer order.
    """

    workspace_id: UUID
    user_id: UUID
    actor_id: UUID | None
    at: datetime


def subscribe(event_type: type[Any], handler: Handler) -> Handler:
    """Idempotent: registering the same handler twice still delivers the event once."""
    handlers = _subscribers.setdefault(event_type, [])
    if handler not in handlers:
        handlers.append(handler)
    return handler


async def emit(event: Any, session: AsyncSession) -> None:
    for handler in _subscribers.get(type(event), []):
        await handler(event, session)
