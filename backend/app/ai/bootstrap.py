"""Installing the model provider at start-up (architecture §10).

Called once by the API lifespan and once by the worker. It is the only place that decides which
gateway the rest of the system will find, and it makes one judgement: without a configured key the
system runs on the deterministic fake and says so, rather than failing on the first assessment.
"""

from __future__ import annotations

import logging

from app.ai.gateway import OpenAIGateway, build_gateway, register_gateway
from app.core.config import Settings

log = logging.getLogger(__name__)


def install(settings: Settings) -> OpenAIGateway | None:
    """Register the provider gateway, or leave the fake in place."""
    gateway = build_gateway(settings)
    if gateway is None:
        log.info(
            "no model provider key is configured; assessments will run on the deterministic "
            "fake gateway"
        )
        return None

    register_gateway(gateway)
    log.info("model provider installed: completion model %s", settings.openai_model)
    return gateway
