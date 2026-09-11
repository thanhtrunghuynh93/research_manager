"""Audit trail: every mutating service call writes one row in its transaction (architecture 5.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Enum, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.context import current_request_id
from app.core.db import Base, UUIDPrimaryKeyMixin
from app.core.types import ActorKind


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_audit_events_target", "target_table", "target_id"),
    )

    workspace_id: Mapped[UUID]
    actor_id: Mapped[UUID | None]
    actor_kind: Mapped[ActorKind] = mapped_column(
        Enum(ActorKind, name="actor_kind", values_callable=lambda e: [m.value for m in e])
    )
    action: Mapped[str] = mapped_column(Text)
    target_table: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID | None]
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())


def write_audit(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    action: str,
    target_table: str,
    target_id: UUID | None,
    actor_id: UUID | None = None,
    actor_kind: ActorKind = ActorKind.USER,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit row to the caller's session; the caller's transaction commits it."""
    event = AuditEvent(
        workspace_id=workspace_id,
        actor_id=actor_id,
        actor_kind=actor_kind,
        action=action,
        target_table=target_table,
        target_id=target_id,
        before=before,
        after=after,
        request_id=current_request_id(),
    )
    session.add(event)
    return event
