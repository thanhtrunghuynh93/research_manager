"""Identity tables: workspaces, users, invitations, sessions, password resets.

Only this module imports these classes; other modules read users through identity.service
(docs/repo_layout.md §3.2). Composite foreign keys carry `workspace_id` so a row can never point at
a record in another workspace (architecture §5.1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin
from app.core.types import Role

ROLE_ENUM = Enum(Role, name="role", values_callable=lambda enum: [m.value for m in enum])


class UserState(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


USER_STATE_ENUM = Enum(
    UserState, name="user_state", values_callable=lambda enum: [m.value for m in enum]
)


def _workspace_scoped_user_fk() -> ForeignKeyConstraint:
    """(workspace_id, user_id) -> users(workspace_id, id): same workspace, enforced by the database."""
    return ForeignKeyConstraint(
        ["workspace_id", "user_id"],
        ["users.workspace_id", "users.id"],
        ondelete="CASCADE",
    )


class Workspace(UUIDPrimaryKeyMixin, Base):
    """The private research workspace. One professor, many students (requirements §1).

    `timezone` is the workspace default used when the reporting module creates its first
    calendar configuration; `calendar_configs` stays the versioned authority for period
    arithmetic (architecture §5.2, REP-01).

    `access_epoch` increments whenever a membership ends, a user is deactivated, or visibility
    changes. Cached answers and snapshots record the epoch they were built under so a stale cache
    cannot outlive the access it was built with (AUTH-03, architecture §6.3).
    """

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, default="Asia/Ho_Chi_Minh")
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, ondelete="SET NULL")
    )
    access_epoch: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class User(UUIDPrimaryKeyMixin, Base):
    """AUTH-01: exactly two roles; accounts are invited, active, or deactivated."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        # Target of every (workspace_id, user_id) composite foreign key in the schema.
        UniqueConstraint("workspace_id", "id"),
        Index("ix_users_workspace_id_role", "workspace_id", "role"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(ROLE_ENUM)
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    state: Mapped[UserState] = mapped_column(USER_STATE_ENUM, default=UserState.INVITED)
    locale: Mapped[str] = mapped_column(Text, default="en", server_default="en")
    deactivated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Invitation(UUIDPrimaryKeyMixin, Base):
    """A single-use enrollment token. The database stores only its digest (architecture §6.2)."""

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        _workspace_scoped_user_fk(),
        Index("ix_invitations_workspace_id_email", "workspace_id", "email"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID]
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(ROLE_ENUM)
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Session(UUIDPrimaryKeyMixin, Base):
    """Server-side session behind an opaque cookie: 12 hour idle, 30 day absolute (AUTH-01)."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        _workspace_scoped_user_fk(),
        Index("ix_sessions_user_id", "user_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class PasswordReset(UUIDPrimaryKeyMixin, Base):
    """AUTH-01 account recovery: a single-use token emailed to the address on the account."""

    __tablename__ = "password_resets"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        _workspace_scoped_user_fk(),
        Index("ix_password_resets_user_id", "user_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]  # superseded by a newer request
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
