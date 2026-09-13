"""The assessment arithmetic (ASSESS-04, ASSESS-05, ASSESS-06, ADR 0006).

Pure functions over plain values: no database, no model, no clock. Language models are unreliable
at weighted sums and rounding and cannot be replayed exactly, so every number a student sees is
computed here and can be recomputed from the stored inputs.

Three rules are worth stating because they are easy to get wrong and unfair when wrong:
an unknown is an absence of evidence and never a zero; a missing baseline makes commitment
completion unavailable rather than zero; and a stale source lowers confidence without lowering a
rating.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal

UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"

RatingValue = int | Literal["unknown", "not_applicable"]

MAX_RATING = 4
HIGH_COVERAGE = Decimal(90)
LOW_COVERAGE = Decimal(70)
CENTS = Decimal("0.01")


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class PlanItem:
    """One frozen commitment and the completion the professor accepted for it."""

    weight: Decimal
    accepted_completion: Decimal


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """What the sources looked like when the assessment was built (ASSESS-06).

    `repository_fresh` is None when the project has no repository at all, which is not a gap: a
    literature or theory project can have full coverage through other artifacts.
    """

    report_submitted: bool
    baseline_available: bool
    repository_fresh: bool | None = None
    unverifiable_claims: int = 0
    truncated_evidence: bool = False
    unresolved_attributions: int = 0
    extra_reasons: list[str] = field(default_factory=list)


def progress_index(
    ratings: Mapping[str, RatingValue], weights: Mapping[str, Decimal]
) -> int | None:
    """ASSESS-04: the 0-100 supervision aid, or None when it must not be shown.

    Returns None — "Not rated, insufficient evidence" — unless every applicable dimension could be
    rated. A dimension marked not-applicable by the rubric drops out and the remaining weights are
    renormalised over what is left.
    """
    applicable: dict[str, int] = {}
    for dimension in weights:
        value = ratings.get(dimension, UNKNOWN)
        if value == NOT_APPLICABLE:
            continue
        if value == UNKNOWN:
            return None
        rating = int(value)
        if not 0 <= rating <= MAX_RATING:
            raise ValueError(f"a rating must be between 0 and {MAX_RATING}, got {rating}")
        applicable[dimension] = rating

    total_weight = sum((weights[d] for d in applicable), Decimal(0))
    if not applicable or total_weight == 0:
        return None

    achieved = sum(
        (weights[d] * Decimal(rating) / Decimal(MAX_RATING) for d, rating in applicable.items()),
        Decimal(0),
    )
    fraction = achieved / total_weight
    return int((fraction * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def plan_completion(items: list[PlanItem] | None) -> Decimal | None:
    """ASSESS-05: weighted completion of the commitments, or None when there is no baseline.

    This measures commitments, not scientific value: a week of rigorous work that abandoned the
    plan for a good reason can score low here and high on the rubric.
    """
    if not items:
        return None

    total_weight = sum((item.weight for item in items), Decimal(0))
    if total_weight == 0:
        return None

    achieved = Decimal(0)
    for item in items:
        if not Decimal(0) <= item.accepted_completion <= Decimal(1):
            raise ValueError("an accepted completion fraction must be within [0, 1]")
        achieved += item.weight * item.accepted_completion

    return (achieved / total_weight * 100).quantize(CENTS, rounding=ROUND_HALF_UP)


def coverage_pct(sufficiency: Mapping[str, bool], weights: Mapping[str, Decimal]) -> Decimal:
    """ASSESS-06: the share of applicable rubric weight supported well enough to rate.

    A dimension absent from `sufficiency` is not applicable and is excluded from both sides, so a
    stage that legitimately has no artifacts is not penalised for having none.
    """
    applicable = {d: w for d, w in weights.items() if d in sufficiency}
    total = sum(applicable.values(), Decimal(0))
    if total == 0:
        return Decimal("0.00")

    supported = sum((w for d, w in applicable.items() if sufficiency[d]), Decimal(0))
    return (supported / total * 100).quantize(CENTS, rounding=ROUND_HALF_UP)


def confidence(coverage: Decimal, status: SourceStatus) -> tuple[Confidence, list[str]]:
    """ASSESS-06: a level and the stated rules that produced it, never a bare probability.

    The reasons are what the professor reads to decide whether to trust the draft, so each one
    names the condition rather than summarising it.
    """
    reasons: list[str] = []
    level = Confidence.HIGH

    if not status.report_submitted:
        reasons.append("no report was submitted for this week")
        level = Confidence.LOW
    if coverage < LOW_COVERAGE:
        reasons.append(f"evidence coverage is {coverage}% of the applicable rubric weight")
        level = Confidence.LOW
    elif coverage < HIGH_COVERAGE:
        reasons.append(f"evidence coverage is {coverage}%, below the {HIGH_COVERAGE}% threshold")
        level = min(level, Confidence.MEDIUM, key=_severity)
    if status.repository_fresh is False:
        # AC-04: this says the evidence is stale, not that no work happened.
        reasons.append("the connected repository has not synced recently, so its evidence is stale")
        level = Confidence.LOW
    if not status.baseline_available:
        reasons.append("no plan baseline was in effect, so commitment completion is unavailable")
        level = Confidence.LOW
    if status.unverifiable_claims:
        reasons.append(
            f"{status.unverifiable_claims} report claim(s) are unverifiable against the available"
            " evidence"
        )
        level = min(level, Confidence.MEDIUM, key=_severity)
    if status.truncated_evidence:
        reasons.append("some evidence was truncated by a size limit and was read only in part")
        level = min(level, Confidence.MEDIUM, key=_severity)
    if status.unresolved_attributions:
        reasons.append(
            f"{status.unresolved_attributions} contribution(s) could not be attributed with"
            " confidence"
        )
        level = min(level, Confidence.MEDIUM, key=_severity)
    reasons.extend(status.extra_reasons)

    return level, reasons


def _severity(level: Confidence) -> int:
    return {Confidence.HIGH: 2, Confidence.MEDIUM: 1, Confidence.LOW: 0}[level]
