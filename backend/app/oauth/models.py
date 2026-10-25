"""OAuth tables: registered clients, authorization codes, tokens (ADR 0025).

Only this module imports these classes. Secrets are stored as SHA-256 digests, like sessions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin


def _user_fk() -> ForeignKeyConstraint:
    """Plain key on users.id: `workspace_id` is where consent happened, and must not follow a move.

    A session's composite key cascades on update and so follows the account (ADR 0014); a token
    that did the same would outlive the move it is supposed to die with (ADR 0025).
    """
    return ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE")


class OAuthClient(UUIDPrimaryKeyMixin, Base):
    """A public client registered dynamically (RFC 7591); PKCE stands in for a secret."""

    __tablename__ = "oauth_clients"
    __table_args__ = (UniqueConstraint("client_id"),)

    client_id: Mapped[str] = mapped_column(Text)
    client_name: Mapped[str] = mapped_column(Text)
    redirect_uris: Mapped[list[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OAuthCode(UUIDPrimaryKeyMixin, Base):
    """A single-use authorization code, bound to its PKCE challenge and redirect URI."""

    __tablename__ = "oauth_codes"
    __table_args__ = (UniqueConstraint("code_hash"), _user_fk())

    code_hash: Mapped[str] = mapped_column(Text)
    client_id: Mapped[UUID] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID]
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OAuthToken(UUIDPrimaryKeyMixin, Base):
    """An access and refresh pair, bound to one user and the workspace they consented in."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("access_hash"),
        UniqueConstraint("refresh_hash"),
        _user_fk(),
        Index("ix_oauth_tokens_user_id", "user_id"),
    )

    access_hash: Mapped[str] = mapped_column(Text)
    refresh_hash: Mapped[str] = mapped_column(Text)
    client_id: Mapped[UUID] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID]
    scope: Mapped[str] = mapped_column(Text)
    access_expires_at: Mapped[datetime]
    refresh_expires_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
