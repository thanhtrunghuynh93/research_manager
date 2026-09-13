"""Request and response models for the identity API. No ORM class crosses this boundary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.types import Role
from app.identity.models import UserState


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    role: Role
    email: str
    display_name: str
    state: UserState
    deactivated_at: datetime | None = None
    created_at: datetime


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    timezone: str
    access_epoch: int


class InvitationOut(BaseModel):
    """The invitation record. The token itself is never part of an API response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime


class InvitationIn(BaseModel):
    email: str
    display_name: str | None = None
    role: Role = Role.STUDENT


class AcceptInvitationIn(BaseModel):
    token: str
    password: str
    display_name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordResetRequestIn(BaseModel):
    email: str


class PasswordResetConfirmIn(BaseModel):
    token: str
    password: str


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class RolePatch(BaseModel):
    role: Role
