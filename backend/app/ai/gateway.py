"""The single seam between this system and a language model (ADR 0007, architecture §10).

Only this module may talk to a model provider. Everything above it — the assessment pipeline, and
later the assistant — asks for a structured result and receives one, so replacing the provider
changes nothing else and a restricted project can be served by a gateway that calls nobody.

Three rules the gateway exists to enforce:
  - retrieved text is data, never instruction, and is framed as such (AC-12);
  - no tool or action is ever exposed to the model, because actions are product endpoints (QA-07);
  - every call records the prompt and model version it used, so a result can be reproduced
    (ASSESS-09).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

Schema = TypeVar("Schema", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class Budget:
    """Cost control (requirements §11). Exceeding it delays the analysis visibly rather than
    failing silently."""

    max_tokens: int = 4096
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class CallContext:
    """What the call was for, recorded alongside the result (ASSESS-09)."""

    prompt_id: str
    prompt_version: str
    project_id: Any = None
    job_id: Any = None
    restricted: bool = False


@dataclass(frozen=True, slots=True)
class Result[Schema]:
    """Either a parsed structured output, or the reason there is none."""

    value: Schema | None
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None


class AIGateway(Protocol):
    async def complete_structured(
        self,
        *,
        prompt_id: str,
        inputs: dict[str, Any],
        schema: type[Schema],
        budget: Budget,
        context: CallContext,
    ) -> Result[Schema]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RestrictedGateway:
    """The gateway a project marked `ai_restricted` gets: it calls nobody and says so.

    The pipeline still builds the snapshot and computes the deterministic metrics; the narrative
    comes back empty and the professor rates by hand (architecture §10).
    """

    model = "restricted"

    async def complete_structured(
        self,
        *,
        prompt_id: str,
        inputs: dict[str, Any],
        schema: type[Schema],
        budget: Budget,
        context: CallContext,
    ) -> Result[Schema]:
        return Result(
            value=None,
            model=self.model,
            prompt_version=context.prompt_version,
            error="restricted",
            notes=["this project does not send content to a model provider"],
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from app.evidence.index.embeddings import DeterministicEmbedder

        return await DeterministicEmbedder().embed(texts)


_gateway: AIGateway | None = None


def register_gateway(gateway: AIGateway) -> AIGateway:
    """Called once at start-up by whoever owns the provider credentials."""
    global _gateway
    _gateway = gateway
    return gateway


def current_gateway() -> AIGateway:
    """The configured gateway, or the fake one, so nothing reaches a provider by accident."""
    if _gateway is None:
        from app.ai.fake import FakeGateway

        return FakeGateway()
    return _gateway
