"""Domain events emitted by identity.service (docs/repo_layout.md §3.2).

Handlers are registered by the modules that react, which keeps identity unaware of them. The
notifications module subscribes to the two token events to send the invitation and recovery emails
(AUTH-01); until it lands nothing is subscribed and `emit` is a no-op.

The plaintext token travels in the event and never in an API response: only the addressee of the
email may learn it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None]]
_subscribers: dict[type[Any], list[Handler]] = {}


@dataclass(frozen=True, slots=True)
class InvitationCreated:
    workspace_id: UUID
    user_id: UUID
    email: str
    display_name: str
    locale: str
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordResetRequested:
    workspace_id: UUID
    user_id: UUID
    email: str
    display_name: str
    locale: str
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UserDeactivated:
    workspace_id: UUID
    user_id: UUID
    actor_id: UUID | None


def subscribe(event_type: type[Any], handler: Handler) -> Handler:
    _subscribers.setdefault(event_type, []).append(handler)
    return handler


async def emit(event: Any) -> None:
    for handler in _subscribers.get(type(event), []):
        await handler(event)
