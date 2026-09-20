"""Audit trail: every mutating service call writes one row in its transaction (architecture 5.3)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Enum, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.context import current_request_id
from app.core.db import Base, UUIDPrimaryKeyMixin
from app.core.types import ActorKind

if TYPE_CHECKING:
    # Under TYPE_CHECKING only: `authz` is a peer inside `app.core` and importing it at runtime
    # here would tie the audit table's module to the permission model for the sake of one
    # annotation. Only `Scope.audit_actor` is touched, and `from __future__ import annotations`
    # keeps the signature readable without it.
    from app.core.authz import Scope


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
    action: str,
    target_table: str,
    target_id: UUID | None,
    scope: Scope | None = None,
    workspace_id: UUID | None = None,
    actor_id: UUID | None = None,
    actor_kind: ActorKind = ActorKind.USER,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit row to the caller's session; the caller's transaction commits it.

    Pass `scope` whenever the write is being made under one. The actor is then taken from
    `Scope.audit_actor`, which is the only thing that knows whether the identity in the Scope is an
    author or a lens: a scheduled task borrows a professor to inherit their visibility (ADR 0011),
    and recording that professor as the author is a claim about who decided something that nobody
    reading the row could tell was false.

    That property existed and was documented before this signature did, and nineteen of the twenty
    call sites reached past it to `scope.user_id` with the default `actor_kind`, so every write a
    periodic task made was attributed to a person. Passing the actor explicitly *alongside* a scope
    is therefore refused rather than merged: the whole point is that `is_system` cannot be talked
    out of.

    `actor_id` and `actor_kind` remain for the writes that have no Scope to speak of — someone
    resetting their own password, a break-glass transfer — where the actor is known directly.
    """
    if scope is not None:
        if actor_id is not None or actor_kind is not ActorKind.USER:
            raise ValueError(
                "write_audit takes either a scope or an explicit actor, not both: "
                "an explicit actor would silently override a system scope"
            )
        actor_id, actor_kind = scope.audit_actor
        workspace_id = workspace_id if workspace_id is not None else scope.workspace_id

    if workspace_id is None:
        raise ValueError("write_audit needs a workspace_id, or a scope to take one from")

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
