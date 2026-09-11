"""A deterministic gateway for tests, the demo seed, and any run that must not reach a provider.

It is not a mock: it produces schema-valid output from the inputs it is given, so the pipeline
around it — validation, metrics, versioning, review — is exercised for real. What it cannot do is
judge research, so its ratings are derived from simple, stated heuristics and are never presented
as a model's opinion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.gateway import Budget, CallContext, Result, Schema
from app.ai.schemas import (
    Claim,
    ClaimList,
    ClaimVerdict,
    ClaimVerdicts,
    DimensionRating,
    RubricOutput,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class FakeGateway:
    """Scripted where a test needs a specific answer, derived where it does not."""

    model: str = "fake-1"
    responses: dict[str, Any] = field(default_factory=dict)
    fail_prompts: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    default_rating: str = "3"

    async def complete_structured(
        self,
        *,
        prompt_id: str,
        inputs: dict[str, Any],
        schema: type[Schema],
        budget: Budget,
        context: CallContext,
    ) -> Result[Schema]:
        self.calls.append(prompt_id)
        if prompt_id in self.fail_prompts:
            return Result(
                value=None,
                model=self.model,
                prompt_version=context.prompt_version,
                error=f"fake failure for {prompt_id}",
            )

        scripted = self.responses.get(prompt_id)
        if scripted is not None:
            value = scripted if isinstance(scripted, schema) else schema.model_validate(scripted)
            return Result(value=value, model=self.model, prompt_version=context.prompt_version)

        built = self._derive(prompt_id, inputs)
        return Result(
            value=schema.model_validate(built.model_dump()) if built else None,
            model=self.model,
            prompt_version=context.prompt_version,
            error=None if built else f"no fake response for {prompt_id}",
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from app.evidence.index.embeddings import DeterministicEmbedder

        return await DeterministicEmbedder().embed(texts)

    # ---------------------------------------------------------------- derivations

    def _derive(self, prompt_id: str, inputs: dict[str, Any]) -> Any:
        if prompt_id == "extract_claims":
            return self._claims(str(inputs.get("entry", "")))
        if prompt_id == "match_claims":
            return self._verdicts(inputs)
        if prompt_id == "rate_rubric":
            return self._rubric(inputs)
        return None

    def _claims(self, entry: str) -> ClaimList:
        sentences = [s.strip() for s in _SENTENCE.split(entry) if len(s.strip()) > 15]
        return ClaimList(claims=[Claim(text=sentence) for sentence in sentences[:10]])

    def _verdicts(self, inputs: dict[str, Any]) -> ClaimVerdicts:
        evidence_ids = [str(item.get("id")) for item in inputs.get("evidence", [])]
        verdicts = []
        for index, claim in enumerate(inputs.get("claims", [])):
            text = claim if isinstance(claim, str) else str(claim.get("text", ""))
            # Supported while evidence remains; unverifiable once it runs out, which is the
            # honest answer rather than a guess (AC-07).
            supporting = evidence_ids[index : index + 1]
            verdicts.append(
                ClaimVerdict(
                    claim=text,
                    status="supported" if supporting else "unverifiable",
                    evidence_ref_ids=supporting,
                    note="" if supporting else "no evidence in the snapshot addresses this claim",
                )
            )
        return ClaimVerdicts(verdicts=verdicts)

    def _rubric(self, inputs: dict[str, Any]) -> RubricOutput:
        dimensions = list(inputs.get("rubric", {}).get("dimensions", {})) or [
            "progress",
            "learning",
            "rigor",
            "artifacts",
        ]
        evidence_ids = [str(item.get("id")) for item in inputs.get("evidence", [])]
        rated = {}
        for dimension in dimensions:
            # Without evidence there is nothing to rate, which is `unknown`, not zero.
            rating = self.default_rating if evidence_ids else "unknown"
            rated[dimension] = DimensionRating(
                rating=rating,  # type: ignore[arg-type]
                rationale=(
                    f"derived from {len(evidence_ids)} piece(s) of evidence in the snapshot"
                    if evidence_ids
                    else "no evidence in the snapshot supports a rating for this dimension"
                ),
                evidence_ref_ids=evidence_ids[:2],
            )
        return RubricOutput(
            dimensions=rated,
            accomplishments=["reported work was read from the entry"] if evidence_ids else [],
            blockers=[],
            discrepancies=[],
            limitations=[] if evidence_ids else ["the snapshot contained no evidence"],
            next_steps=[],
            discussion_agenda=[],
        )
