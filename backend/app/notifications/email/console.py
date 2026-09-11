"""Development sender: writes to the log and to an in-process outbox the e2e suite reads."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.notifications.email.base import DeliveryResult

log = logging.getLogger(__name__)


@dataclass
class SentEmail:
    to: str
    template: str
    params: dict[str, Any]
    idempotency_key: str


@dataclass
class ConsoleEmailSender:
    outbox: list[SentEmail] = field(default_factory=list)

    async def send(
        self, to: str, template: str, params: dict[str, Any], idempotency_key: str
    ) -> DeliveryResult:
        self.outbox.append(SentEmail(to, template, params, idempotency_key))
        log.info("email %s -> %s (key %s)", template, to, idempotency_key)
        return DeliveryResult(accepted=True)
