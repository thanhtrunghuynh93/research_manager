"""Response models for notification records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    recipient_id: UUID
    kind: str
    subject_table: str
    subject_id: UUID | None = None
    period_id: UUID | None = None
    payload: dict[str, Any]
    read_at: datetime | None = None
    created_at: datetime
