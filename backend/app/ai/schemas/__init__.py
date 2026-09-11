"""Structured outputs the gateway enforces (architecture §9.3).

The model returns JSON matching these models or the result is rejected. Nothing here accepts free
prose where a decision is expected: a rating is one of five values or the word `unknown`, and every
claim about the work carries the evidence it rests on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
    """`not_applicable` is deliberately absent: only the rubric may decide that (ASSESS-04)."""

    rating: RatingLiteral
    rationale: str
    evidence_ref_ids: list[str] = Field(default_factory=list)


class PlanItemAssessment(BaseModel):
    task_id: str
    proposed_completion: float = Field(ge=0, le=1)
    reason: str
    evidence_ref_ids: list[str] = Field(default_factory=list)


class RubricOutput(BaseModel):
    """What the rating step must return (architecture §9.3)."""

    dimensions: dict[str, DimensionRating] = Field(default_factory=dict)
    plan_items: list[PlanItemAssessment] = Field(default_factory=list)
    accomplishments: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    discrepancies: list[ClaimVerdict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    discussion_agenda: list[str] = Field(default_factory=list)
