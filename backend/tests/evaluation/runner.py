"""Running one evaluation case through the prompts and the deterministic metrics.

Deliberately not the full database pipeline. What the evaluation set exercises is the part that can
be wrong in interesting ways — the three prompt steps, the validation that drops a fabricated
citation, and the arithmetic that decides whether an index may be shown at all. Fabricating ten
database worlds to reach the same three calls would test the fixtures, not the assessor.
"""

from __future__ import annotations

from decimal import Decimal

from app.ai.gateway import AIGateway, Budget, CallContext
from app.ai.prompts.registry import load as load_prompt
from app.ai.schemas import ClaimList, ClaimVerdicts, RubricOutput
from app.assessment.metrics import UNKNOWN, progress_index
from app.assessment.service import DEFAULT_DIMENSIONS, validate_output
from tests.evaluation.harness import Case, Outcome

WEIGHTS = {name: Decimal(str(spec["weight"])) for name, spec in DEFAULT_DIMENSIONS.items()}


async def run_case(case: Case, gateway: AIGateway) -> Outcome:
    evidence = [
        {"id": doc.evidence_id, "text": doc.text, "locator": doc.name} for doc in case.evidence
    ]

    claims = await _call(gateway, "extract_claims", {"entry": case.report}, ClaimList)
    if not claims.ok:
        return _failed(case, f"extract_claims: {claims.error}")

    verdicts = await _call(
        gateway,
        "match_claims",
        {"claims": [claim.model_dump() for claim in claims.value.claims], "evidence": evidence},
        ClaimVerdicts,
    )
    if not verdicts.ok:
        return _failed(case, f"match_claims: {verdicts.error}")

    rating = await _call(
        gateway,
        "rate_rubric",
        {
            "rubric": {"dimensions": DEFAULT_DIMENSIONS},
            # The real shape: a list of addressable commitments. The evaluation set has none.
            "baseline": [],
            "entry": case.report,
            "evidence": evidence,
            "verdicts": [verdict.model_dump() for verdict in verdicts.value.verdicts],
        },
        RubricOutput,
    )
    if not rating.ok:
        return _failed(case, f"rate_rubric: {rating.error}")

    validated = validate_output(
        rating.value,
        allowed_evidence_ids=case.evidence_ids,
        allowed_dimensions=set(DEFAULT_DIMENSIONS),
    )
    ratings = {name: value["rating"] for name, value in validated.items()}

    cited: set[str] = set()
    for value in validated.values():
        cited.update(value["evidence_ref_ids"])
    for verdict in verdicts.value.verdicts:
        cited.update(verdict.evidence_ref_ids)

    return Outcome(
        case_id=case.case_id,
        stage=case.stage,
        ratings=ratings,
        progress_index=progress_index(ratings, WEIGHTS),
        plan_completion=None,
        text=_narrative(rating.value, validated),
        # Only ids the model actually produced; `validate_output` has already dropped the
        # fabricated ones from the ratings, so the union with the verdicts is what it tried to cite.
        cited_ids=cited,
        claim_statuses={verdict.claim: verdict.status for verdict in verdicts.value.verdicts},
    )


async def _call(
    gateway: AIGateway, prompt_id: str, inputs: dict[str, object], schema: type[object]
) -> object:
    prompt = load_prompt(prompt_id, "v1")
    return await gateway.complete_structured(
        prompt_id=prompt_id,
        inputs=inputs,
        schema=schema,  # type: ignore[arg-type]
        budget=Budget(max_tokens=prompt.max_tokens),
        context=CallContext(prompt_id=prompt_id, prompt_version=prompt.version),
    )


def _narrative(output: RubricOutput, validated: dict[str, dict[str, object]]) -> str:
    """Everything a professor or a student would read, so `must_not_appear` covers all of it."""
    parts: list[str] = []
    parts.extend(output.accomplishments)
    parts.extend(output.blockers)
    parts.extend(output.limitations)
    parts.extend(output.next_steps)
    parts.extend(output.discussion_agenda)
    parts.extend(verdict.note for verdict in output.discrepancies)
    parts.extend(str(value.get("rationale", "")) for value in validated.values())
    return "\n".join(part for part in parts if part)


def _failed(case: Case, error: str) -> Outcome:
    return Outcome(
        case_id=case.case_id,
        stage=case.stage,
        ratings=dict.fromkeys(WEIGHTS, UNKNOWN),
        progress_index=None,
        plan_completion=None,
        text="",
        error=error,
    )
