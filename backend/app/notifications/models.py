"""Notification tables: notification records, email delivery state, reminder rules.

Requirements REP-07, REP-08, UI-07. The unique indexes are what make a retried job harmless: a
second attempt inserts nothing and therefore sends nothing (AC-19).

Preferences are gone: use cases v0.4 withdrew muting with the screen that offered it, and migration
0017 dropped the table. Records are still written for every kind, but since the same version
withdrew the in-app surface only `missed_deadline` reaches a person, by email — see
`notifications/service.py` and architecture §7.3.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


class DeliveryState(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


DELIVERY_STATE_ENUM = Enum(
    DeliveryState, name="delivery_state", values_callable=lambda e: [m.value for m in e]
)


class Notification(UUIDPrimaryKeyMixin, Base):
    """One message for one recipient.

    `kind` is free text from the vocabulary in notifications.service, because the pre-deadline
    reminders carry their offset in the kind (`reminder:48h`) and the offsets are configurable
    (architecture §7.3).
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of the email_deliveries composite key
        ForeignKeyConstraint(
            ["workspace_id", "recipient_id"],
            ["users.workspace_id", "users.id"],
            ondelete="CASCADE",
            # Follows the recipient when they join another workspace (ADR 0014). A notification is
            # addressed to a person, and the alternative is refusing the move for anyone who has
            # ever been sent one — which, eventually, is everyone.
            onupdate="CASCADE",
        ),
        # One per recipient, period, kind and subject — the guard that makes a retried job a
        # no-op. The subject is part of it because a week can hold more than one of some kinds: a
        # second revision request, on another project or after an insufficient fix, is a second
        # thing to say. Without it that message collided with the first and was dropped, for a
        # kind students are deliberately not allowed to mute (REP-05, UI-07).
        Index(
            "uq_notification",
            "recipient_id",
            "period_id",
            "kind",
            "subject_id",
            unique=True,
            postgresql_where=text("period_id IS NOT NULL"),
        ),
        Index(
            "uq_notification_subject",
            "recipient_id",
            "kind",
            "subject_id",
            unique=True,
            postgresql_where=text("period_id IS NULL"),
        ),
        Index("ix_notifications_recipient_id_created_at", "recipient_id", "created_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    recipient_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(Text)
    subject_table: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID | None]
    period_id: Mapped[UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EmailDelivery(Base):
    """REP-08: the delivery state of one notification's email, with its bounded retries."""

    __tablename__ = "email_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "notification_id"],
            ["notifications.workspace_id", "notifications.id"],
            ondelete="CASCADE",
        ),
        Index("ix_email_deliveries_state", "state"),
    )

    notification_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    recipient_email: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    state: Mapped[DeliveryState] = mapped_column(DELIVERY_STATE_ENUM, default=DeliveryState.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReminderRule(UUIDPrimaryKeyMixin, Base):
    """REP-07: how long before the deadline an in-app reminder is raised."""

    __tablename__ = "reminder_rules"
    __table_args__ = (UniqueConstraint("workspace_id", "offset_minutes"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    offset_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
