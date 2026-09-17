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
    owner_id: UUID | None = None
    archived_at: datetime | None = None
    # Whether the caller belongs to this workspace, which is not the same as owning it and not the
    # same as working in it: a professor may own one they have left, and belongs to several while
    # working in one (ADR 0015). Only `list_workspaces` fills it in; elsewhere it is not asked.
    joined: bool = False


class MoveStudentIn(BaseModel):
    """Where to move a student to. Only a student who has not started work can be moved."""

    workspace_id: UUID


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", min_length=1, max_length=100)


class WorkspaceUpdateIn(BaseModel):
    """Both optional: sending neither is a no-op rather than an error."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)


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
    """`role` is the role the account is created with. A professor may invite a colleague as a
    professor; after acceptance the role no longer moves (ADR 0011)."""

    email: str
    display_name: str | None = None
    role: Role = Role.STUDENT
    # Which workspace the invitation enrols into. Omitted means the caller's own, which is what it
    # always meant implicitly; naming one is required once a professor administers more than one.
    workspace_id: UUID | None = None


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
