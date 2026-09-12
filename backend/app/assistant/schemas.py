"""The answer contract, and the request and response models around it (QA-03, QA-05).

The shape here is the product commitment: an answer says what it looked at, separates what it read
from what it inferred, links every citation to something the reader can actually open, and names
what it could not establish. A field left empty is part of the answer — `gaps` being empty means
"nothing was missing", and that is a claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.models import MessageRole as MessageRole


class AnswerScope(BaseModel):
    """QA-05: what the answer was about, rendered beside it so a follow-up is unambiguous."""

    student_id: UUID | None = None
    student_name: str = ""
    project_id: UUID | None = None
    project_name: str = ""
    since: datetime | None = None
    until: datetime | None = None
    as_of: datetime
    role: Literal["prof", "student"]

    def key(self) -> str:
        return "|".join(
            str(value)
            for value in (
                self.student_id,
                self.project_id,
                self.since,
                self.until,
                self.as_of,
                self.role,
            )
        )


class CitationOut(BaseModel):
    """QA-03: a citation must open an authorized record, so it carries its locator and version."""

    source_kind: str
    source_id: UUID
    source_version: str = ""
    locator: str = ""
    label: str = ""
    # False when a re-check at render time finds the caller can no longer open it
    # (architecture §6.3).
    available: bool = True


class FactOut(BaseModel):
    """A computed value with the function behind it, kept separate from prose (QA-02)."""

    name: str
    label: str
    value: Any
    as_of: datetime
    rows: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""


class AnswerOut(BaseModel):
    """The whole contract. Everything a reader needs to decide how much to trust this."""

    id: UUID
    # The conversation this turn belongs to. `id` identifies the answer and changes every turn;
    # this is what a follow-up passes back as `AskIn.conversation_id` (QA-05).
    conversation_id: UUID | None = None
    question: str
    scope: AnswerScope
    time_range: str
    # The short answer. For a fact question this is rendered from the fact, not generated.
    answer: str
    # Read from the records: each item points at a fact or a citation.
    facts: list[FactOut] = Field(default_factory=list)
    # Inferred by a model from the above. Rendered differently in the UI for a reason (QA-03).
    synthesis: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    # What is missing, stale, or contradictory (QA-04).
    gaps: list[str] = Field(default_factory=list)
    # Set when names or scope were too ambiguous to answer; the answer is then the question.
    clarifying_question: str = ""
    cached: bool = False
    generated_at: datetime
    model_name: str = ""
    prompt_versions: dict[str, str] = Field(default_factory=dict)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None
    student_id: UUID | None = None
    project_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    as_of: datetime | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    scope: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: MessageRole
    body: str
    answer: dict[str, Any]
    created_at: datetime
