"""oauth: clients, authorization codes and tokens for the MCP connector

ADR 0025. A professor authorises a connector (Claude) to read their workspace over MCP. The app is
its own authorization server: `oauth_clients` holds dynamically registered public clients,
`oauth_codes` the single-use PKCE codes, `oauth_tokens` the access and refresh pair. Secrets are
stored as SHA-256 digests only, as sessions are. A token row names the user and the workspace it was
bound to at consent; unlike a session it does not follow the account into another workspace.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _user_fk(table: str) -> list[sa.ForeignKeyConstraint]:
    """A plain key on users.id, with no workspace in it and no `ON UPDATE CASCADE`.

    Sessions use the composite key and follow the account into a new workspace (ADR 0014). A token
    must not: `workspace_id` here is the workspace the professor consented in, and the token is
    dead once the account is elsewhere (ADR 0025). Cascading would rewrite it and keep it alive.
    """
    return [
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f(f"fk_{table}_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{table}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
        sa.UniqueConstraint("client_id", name=op.f("uq_oauth_clients_client_id")),
    )

    op.create_table(
        "oauth_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_codes_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        *_user_fk("oauth_codes"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_oauth_codes_code_hash")),
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("access_hash", sa.Text(), nullable=False),
        sa.Column("refresh_hash", sa.Text(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_tokens_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        *_user_fk("oauth_tokens"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_tokens")),
        sa.UniqueConstraint("access_hash", name=op.f("uq_oauth_tokens_access_hash")),
        sa.UniqueConstraint("refresh_hash", name=op.f("uq_oauth_tokens_refresh_hash")),
    )
    op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_user_id", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
