"""Structured outputs the gateway enforces (architecture §9.3).

The model returns JSON matching these models or the result is rejected. Nothing here accepts free
prose where a decision is expected: a rating is one of five values or the word `unknown`, and every
claim about the work carries the evidence it rests on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RatingLiteral = Literal["0", "1", "2", "3", "4", "unknown"]
ClaimStatus = Literal["supported", "partially_supported", "unsupported", "unverifiable"]


class Claim(BaseModel):
    """One factual assertion the student made, lifted verbatim so it can be checked."""

    text: str
    field: str = ""
    kind: Literal["result", "artifact", "process", "blocker", "plan"] = "result"


class ClaimList(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class ClaimVerdict(BaseModel):
    claim: str
    status: ClaimStatus
    evidence_ref_ids: list[str] = Field(default_factory=list)
    note: str = ""


class ClaimVerdicts(BaseModel):
    verdicts: list[ClaimVerdict] = Field(default_factory=list)


class DimensionRating(BaseModel):
    """`not_applicable` is deliberately absent: only the rubric may decide that (ASSESS-04).

    `dimension_id` is the rubric dimension this rates, copied from the rubric supplied in the
    prompt. It is a field rather than a mapping key because the provider's strict mode cannot
    express an open-ended map — see `app.ai.schemas.strict`.
    """

    dimension_id: str
    rating: RatingLiteral
    rationale: str
    evidence_ref_ids: list[str] = Field(default_factory=list)


class PlanItemAssessment(BaseModel):
    """One frozen commitment, and how far the draft says it got (ASSESS-05).

    `item_id` is the plan baseline item's id, which is what the prompt supplies; every baseline
    item has one, where `task_id` is optional and cannot address the whole plan.
    """

    item_id: str
    # The range is enforced here rather than declared on the field: `ge`/`le` reach the wire as
    # `minimum`/`maximum`, which strict mode may refuse, and a bound the provider ignores is worth
    # nothing anyway. Clamping rather than raising is deliberate — `metrics.plan_completion` raises
    # on a fraction outside [0, 1], so letting one through would turn a recoverable PARTIAL run
    # into an unhandled exception in the worker.
    proposed_completion: float
    reason: str
    evidence_ref_ids: list[str] = Field(default_factory=list)

    @field_validator("proposed_completion", mode="after")
    @classmethod
    def _within_unit_interval(cls, value: float) -> float:
        return min(1.0, max(0.0, value))


class RubricOutput(BaseModel):
    """What the rating step must return (architecture §9.3).

    `dimensions` is a list, not a map keyed by dimension id. The map was the shape the rubric
    itself has and it read better, but it made this the one schema the provider refused: strict
    mode has no way to express an object whose keys are not known in advance, so every call
    carrying it came back 400 and no assessment was ever produced from real model output.
    `validate_output` turns the list back into a map, so nothing downstream — including what is
    already stored in `assessment_versions.ratings` — sees the difference.
    """

    dimensions: list[DimensionRating] = Field(default_factory=list)
    plan_items: list[PlanItemAssessment] = Field(default_factory=list)
    accomplishments: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    discrepancies: list[ClaimVerdict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    discussion_agenda: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ the assistant (§11)


class RoutePlan(BaseModel):
    """What the router decided: which facts to compute, what to search for, and about whom.

    Entities come back as the names the asker used. They are resolved against the database before
    anything is read, so a name the model invented finds nothing rather than reaching a record
    (architecture §11).
    """

    intent: Literal["fact", "narrative", "mixed", "clarify"] = "mixed"
    fact_functions: list[str] = Field(default_factory=list)
    student_names: list[str] = Field(default_factory=list)
    project_names: list[str] = Field(default_factory=list)
    # A free-text search over report and repository evidence; empty for a pure fact question.
    search_query: str = ""
    # ISO dates when the question named a period; the service resolves relative phrases itself.
    since: str = ""
    until: str = ""
    as_of: str = ""
    # Set when a name or a scope is ambiguous. QA-05: ask rather than guess.
    clarifying_question: str = ""


class AnswerSection(BaseModel):
    """One statement, with the evidence it rests on. Empty ids mean it rests on the facts given."""

    text: str
    evidence_ref_ids: list[str] = Field(default_factory=list)


class AnswerDraft(BaseModel):
    """What the generation step must return (QA-03).

    `facts_used` and `synthesis` are separate fields because they are different kinds of claim and
    the reader is entitled to see which is which.
    """

    answer: str
    synthesis: list[AnswerSection] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    cited_evidence_ref_ids: list[str] = Field(default_factory=list)
