"""Assistant tables: conversations, messages, and the answer cache (architecture §5.1, §11).

Research records live in their own tables and are never derived from chat history (QA-05). A
conversation here is a record of what was asked and what was answered — it is not where anything
is known.

The cache carries the access epoch it was built under. That single column is what makes AC-11
possible: when a membership ends the epoch advances, and every answer computed under the old one
stops being served without anything having to find and delete it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


MESSAGE_ROLE_ENUM = Enum(
    MessageRole, name="message_role", values_callable=lambda enum: [m.value for m in enum]
)


class Conversation(UUIDPrimaryKeyMixin, Base):
    """QA-05: the active scope is explicit and persisted, so a follow-up knows what it follows."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        Index("ix_conversations_owner", "owner_id", "created_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    owner_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(Text, default="")
    # {student_id, project_id, since, until, as_of} — what "that" and "last month" resolve against.
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Message(UUIDPrimaryKeyMixin, Base):
    """One turn. An assistant turn stores the whole answer contract, not just its prose."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "created_at"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    conversation_id: Mapped[UUID]
    role: Mapped[MessageRole] = mapped_column(MESSAGE_ROLE_ENUM)
    body: Mapped[str] = mapped_column(Text, default="")
    # The full answer: time range, scope, facts, synthesis, suggestions, citations, gaps (QA-03).
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AnswerCache(UUIDPrimaryKeyMixin, Base):
    """AC-11: an answer cached under an access epoch dies with that epoch.

    Keyed by the asker as well as the question: two people may ask the same words and be entitled
    to different answers, and a cache shared between them would be the leak (QA-06).
    """

    __tablename__ = "answer_cache"
    __table_args__ = (
        UniqueConstraint("user_id", "question_hash", "scope_hash", name="uq_answer_cache_key"),
        Index("ix_answer_cache_epoch", "workspace_id", "access_epoch"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID]
    question_hash: Mapped[str] = mapped_column(Text)
    scope_hash: Mapped[str] = mapped_column(Text)
    access_epoch: Mapped[int] = mapped_column(Integer)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
