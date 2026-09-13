"""evidence: repositories, sync runs, events, identities, contributions

Requirements REPO-01..08; architecture sections 8.1 to 8.5.

Revision ID: f78fec60dedf
Revises: 0007
Create Date: 2026-09-11 18:46:03.660764+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPOSITORY_EVENT_GUARD = """
CREATE OR REPLACE FUNCTION guard_repository_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'repository_events rows are immutable: DELETE not allowed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- Compare every column except the one the system is allowed to observe.
    IF ROW(
        NEW.workspace_id, NEW.repository_id, NEW.provider_event_id, NEW.kind, NEW.source_version,
        NEW.title, NEW.actors, NEW.authored_at, NEW.committed_at, NEW.merged_at, NEW.event_at,
        NEW.ingested_at, NEW.paths, NEW.stats, NEW.payload_key, NEW.truncated, NEW.source_url
    ) IS DISTINCT FROM ROW(
        OLD.workspace_id, OLD.repository_id, OLD.provider_event_id, OLD.kind, OLD.source_version,
        OLD.title, OLD.actors, OLD.authored_at, OLD.committed_at, OLD.merged_at, OLD.event_at,
        OLD.ingested_at, OLD.paths, OLD.stats, OLD.payload_key, OLD.truncated, OLD.source_url
    ) THEN
        RAISE EXCEPTION 'repository_events is immutable: only live_available may change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column(
            "connection_state",
            sa.Enum("connected", "unauthorized", "disconnected", name="connection_state"),
            nullable=False,
        ),
        sa.Column("credential_ref", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.Text(), nullable=True),
        sa.Column("connected_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_repositories_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_repositories_workspace_id_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_id",
            name=op.f("uq_repositories_workspace_id_provider_external_id"),
        ),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("delivery_id", sa.Text(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("external_repo_id", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_webhook_deliveries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
        sa.UniqueConstraint(
            "provider", "delivery_id", name=op.f("uq_webhook_deliveries_provider_delivery_id")
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_received_at", "webhook_deliveries", ["received_at"], unique=False
    )
    op.create_table(
        "developer_identities",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("login", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "verification",
            sa.Enum(
                "pending",
                "verified_oauth",
                "confirmed_by_student",
                "confirmed_by_prof",
                "rejected",
                name="identity_verification",
            ),
            nullable=False,
        ),
        sa.Column("is_bot", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            name=op.f("fk_developer_identities_workspace_id_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_developer_identities_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_developer_identities")),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "email",
            name=op.f("uq_developer_identities_workspace_id_provider_email"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "login",
            name=op.f("uq_developer_identities_workspace_id_provider_login"),
        ),
    )
    op.create_index(
        "ix_developer_identities_student_id", "developer_identities", ["student_id"], unique=False
    )
    op.create_table(
        "project_repositories",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("path_rules", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_project_repositories_workspace_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "repository_id"],
            ["repositories.workspace_id", "repositories.id"],
            name=op.f("fk_project_repositories_workspace_id_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_project_repositories_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_repositories")),
        sa.UniqueConstraint(
            "repository_id",
            "project_id",
            name=op.f("uq_project_repositories_repository_id_project_id"),
        ),
    )
    op.create_table(
        "repository_events",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "commit",
                "pr_opened",
                "pr_merged",
                "review",
                "issue",
                "check_run",
                "push_force",
                name="event_kind",
            ),
            nullable=False,
        ),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("actors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("paths", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_key", sa.Text(), nullable=True),
        sa.Column("truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("live_available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "repository_id"],
            ["repositories.workspace_id", "repositories.id"],
            name=op.f("fk_repository_events_workspace_id_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_repository_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repository_events")),
        sa.UniqueConstraint(
            "repository_id",
            "provider_event_id",
            name=op.f("uq_repository_events_repository_id_provider_event_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_repository_events_workspace_id_id")
        ),
    )
    op.create_index(
        "ix_repository_events_repository_id_event_at",
        "repository_events",
        ["repository_id", "event_at"],
        unique=False,
    )
    op.create_index(
        "ix_repository_events_source_version", "repository_events", ["source_version"], unique=False
    )
    op.create_table(
        "sync_runs",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("repository_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("initial", "incremental", "webhook", "manual", name="sync_kind"),
            nullable=False,
        ),
        sa.Column(
            "state",
            sa.Enum("queued", "running", "completed", "partial", "failed", name="sync_state"),
            nullable=False,
        ),
        sa.Column("watermark", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pages_done", sa.Integer(), nullable=False),
        sa.Column("events_ingested", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "repository_id"],
            ["repositories.workspace_id", "repositories.id"],
            name=op.f("fk_sync_runs_workspace_id_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_sync_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_index(
        "ix_sync_runs_repository_id_started_at",
        "sync_runs",
        ["repository_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "contributions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column(
            "role",
            sa.Enum("author", "committer", "reviewer", "merger", name="contribution_role"),
            nullable=False,
        ),
        sa.Column(
            "share", sa.Enum("individual", "joint", name="contribution_share"), nullable=False
        ),
        sa.Column(
            "attribution_state",
            sa.Enum(
                "resolved", "unresolved_identity", "unresolved_project", name="attribution_state"
            ),
            nullable=False,
        ),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "event_id"],
            ["repository_events.workspace_id", "repository_events.id"],
            name=op.f("fk_contributions_workspace_id_event_id_repository_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            name=op.f("fk_contributions_workspace_id_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_contributions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contributions")),
        sa.UniqueConstraint(
            "event_id", "student_id", "role", name=op.f("uq_contributions_event_id_student_id_role")
        ),
    )
    op.create_index(
        "ix_contributions_student_id_project_id",
        "contributions",
        ["student_id", "project_id"],
        unique=False,
    )

    # REPO-05/AC-09: an event we have attributed and cited cannot change underneath it.
    # REPO-06 still has to record that a force push removed the object upstream, so the guard
    # admits exactly one change: `live_available`, which is our observation rather than their fact.
    op.execute(REPOSITORY_EVENT_GUARD)
    op.execute(
        "CREATE TRIGGER trg_guard_repository_event BEFORE UPDATE OR DELETE ON repository_events "
        "FOR EACH ROW EXECUTE FUNCTION guard_repository_event()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_guard_repository_event ON repository_events")
    op.execute("DROP FUNCTION IF EXISTS guard_repository_event()")
    op.drop_index("ix_contributions_student_id_project_id", table_name="contributions")
    op.drop_table("contributions")
    op.drop_index("ix_sync_runs_repository_id_started_at", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_index("ix_repository_events_source_version", table_name="repository_events")
    op.drop_index("ix_repository_events_repository_id_event_at", table_name="repository_events")
    op.drop_table("repository_events")
    op.drop_table("project_repositories")
    op.drop_index("ix_developer_identities_student_id", table_name="developer_identities")
    op.drop_table("developer_identities")
    op.drop_index("ix_webhook_deliveries_received_at", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_table("repositories")
    for enum_name in (
        "attribution_state",
        "contribution_share",
        "contribution_role",
        "identity_verification",
        "event_kind",
        "sync_state",
        "sync_kind",
        "connection_state",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
