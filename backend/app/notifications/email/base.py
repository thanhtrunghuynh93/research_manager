"""The mail boundary (architecture §13).

Templates receive only identifiers, dates, and the recipient's own missing-entry list. Assessment
narratives and other students' names never reach an email (REP-08, UI-07).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    accepted: bool
    detail: str = ""


class EmailSender(Protocol):
    async def send(
        self, to: str, template: str, params: dict[str, Any], idempotency_key: str
    ) -> DeliveryResult:
        """Deliver one message. The key lets a provider collapse a retried send."""
        ...
