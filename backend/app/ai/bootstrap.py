"""Installing the model provider at start-up (architecture §10).

Called once by the API lifespan and once by the worker. It is the only place that decides which
gateway the rest of the system will find, and it makes one judgement: without a configured key the
system runs on the deterministic fake and says so, rather than failing on the first assessment.

It also registers the embedder, which is why `app.evidence` never imports `app.ai`: the index asks
for whatever embedder is registered, and this module supplies the gateway-backed one when there is
a provider to back it (docs/repo_layout.md §3.3, architecture §5.7).
"""

from __future__ import annotations

import logging

from app.ai.gateway import OpenAIGateway, build_gateway, register_gateway
from app.core.config import Settings
from app.evidence.index.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbedContext,
    register_embedder,
)

log = logging.getLogger(__name__)


class GatewayEmbedder:
    """The index's `Embedder`, backed by the gateway, with the billing context passed through."""

    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, gateway: OpenAIGateway) -> None:
        self.gateway = gateway

    async def embed(
        self, texts: list[str], *, context: EmbedContext | None = None
    ) -> list[list[float]]:
        return await self.gateway.embed(
            texts,
            workspace_id=None if context is None else context.workspace_id,
            project_id=None if context is None else context.project_id,
            session=None if context is None else context.session,
        )


def install(settings: Settings) -> OpenAIGateway | None:
    """Register the provider gateway and embedder, or leave the fakes in place."""
    gateway = build_gateway(settings)
    if gateway is None:
        log.info(
            "no model provider key is configured; assessments will run on the deterministic "
            "fake gateway and the local embedder"
        )
        return None

    register_gateway(gateway)
    register_embedder(GatewayEmbedder(gateway))
    log.info(
        "model provider installed: completion model %s, embedding model %s",
        settings.openai_model,
        settings.openai_embed_model,
    )
    return gateway
