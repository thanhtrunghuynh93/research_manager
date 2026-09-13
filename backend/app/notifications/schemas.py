"""Request and response models for the notifications API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    kind: str
    muted_at: datetime


class MuteIn(BaseModel):
    kind: str = Field(min_length=1, max_length=100)


class ReminderOffsetsIn(BaseModel):
    offsets_hours: list[int] = Field(default_factory=lambda: [48, 6])
