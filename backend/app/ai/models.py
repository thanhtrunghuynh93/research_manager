"""The cost ledger (architecture §10, requirements §11 "Cost control").

One row per provider call, successful or not. The tokens are a fact the provider reported; the
cost is an arithmetic consequence of a published rate, and is left null when the rate for that
model is not known rather than guessed.

`project_id` is recorded without a foreign key: the ledger observes which project a call was made
for, it does not own the project, and a retention sweep that removes a project must not be blocked
by an accounting row (docs/repo_layout.md §3.2).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class CallStatus(StrEnum):
    """Why the row exists. `delayed_budget` is the visible state requirements §11 asks for."""

    COMPLETED = "completed"
    FAILED = "failed"
    INVALID_OUTPUT = "invalid_output"
    DELAYED_BUDGET = "delayed_budget"
    RESTRICTED = "restricted"


CALL_STATUS_ENUM = Enum(
    CallStatus, name="ai_call_status", values_callable=lambda enum: [m.value for m in enum]
)


class AiCall(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_calls"
    __table_args__ = (
        Index("ix_ai_calls_workspace_created", "workspace_id", "created_at"),
        Index("ix_ai_calls_project_created", "project_id", "created_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None]
    job_id: Mapped[str | None] = mapped_column(Text)
    prompt_id: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    # Null means "this model has no published rate here", not "this call was free".
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CallStatus] = mapped_column(CALL_STATUS_ENUM, default=CallStatus.COMPLETED)
    # Rule names only, never the text that matched them.
    redactions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
