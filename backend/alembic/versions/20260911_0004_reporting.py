"""reporting: calendar, periods, obligations, reports, versions, entries

Requirements REP-01..06; architecture sections 5.1, 5.2, 5.3, 7.1.

Revision ID: 96ab412ec0b7
Revises: 0003
Create Date: 2026-09-11 17:55:36.623384+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Architecture 5.3: a submitted version and its entries cannot be edited out from under the
# assessment that cites them.
IMMUTABLE_TABLES = ("report_versions", "project_report_entries")

# REP-07 / AC-13: the first submission time is written once. A revision request, a reminder, or a
# later version must not move it.
FIRST_SUBMITTED_AT_IS_WRITE_ONCE = """
CREATE OR REPLACE FUNCTION freeze_first_submitted_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.first_submitted_at IS NOT NULL
       AND NEW.first_submitted_at IS DISTINCT FROM OLD.first_submitted_at THEN
        RAISE EXCEPTION 'first_submitted_at is write-once and cannot be changed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "calendar_configs",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("meeting_weekday", sa.SmallInteger(), nullable=False),
        sa.Column("week_start_weekday", sa.SmallInteger(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
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
            name=op.f("fk_calendar_configs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_configs")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_calendar_configs_workspace_id_id")),
        sa.UniqueConstraint(
            "workspace_id", "version", name=op.f("uq_calendar_configs_workspace_id_version")
        ),
    )
    op.create_index(
        "ix_calendar_configs_workspace_id_effective_from",
        "calendar_configs",
        ["workspace_id", "effective_from"],
        unique=False,
    )
    op.create_table(
        "reporting_periods",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("calendar_config_id", sa.UUID(), nullable=False),
        sa.Column("local_start", sa.Date(), nullable=False),
        sa.Column("local_end", sa.Date(), nullable=False),
        sa.Column("start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meeting_date", sa.Date(), nullable=False),
        sa.Column("deadline_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_due_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_dispatched_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_reporting_periods_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reporting_periods")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_reporting_periods_workspace_id_id")
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "local_start",
            name=op.f("uq_reporting_periods_workspace_id_local_start"),
        ),
    )
    op.create_index(
        "ix_reporting_periods_workspace_id_deadline_utc",
        "reporting_periods",
        ["workspace_id", "deadline_utc"],
        unique=False,
    )
    op.create_table(
        "weekly_reports",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column(
            "workflow_state",
            sa.Enum(
                "draft",
                "submitted",
                "revision_requested",
                "resubmitted",
                "reviewed",
                name="report_state",
            ),
            nullable=False,
        ),
        sa.Column("first_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column("draft_content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("draft_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            name=op.f("fk_weekly_reports_workspace_id_period_id_reporting_periods"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "student_id"],
            ["users.workspace_id", "users.id"],
            name=op.f("fk_weekly_reports_workspace_id_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_weekly_reports_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_reports")),
        sa.UniqueConstraint(
            "student_id", "period_id", name=op.f("uq_weekly_reports_student_id_period_id")
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_weekly_reports_workspace_id_id")),
    )
    op.create_index(
        "ix_weekly_reports_period_id_workflow_state",
        "weekly_reports",
        ["period_id", "workflow_state"],
        unique=False,
    )
    op.create_table(
        "report_versions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "timing_status",
            sa.Enum("on_time", "late", "excused", name="timing_status"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["weekly_reports.workspace_id", "weekly_reports.id"],
            name=op.f("fk_report_versions_workspace_id_report_id_weekly_reports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_report_versions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_versions")),
        sa.UniqueConstraint(
            "report_id",
            "idempotency_key",
            name=op.f("uq_report_versions_report_id_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "report_id", "version_no", name=op.f("uq_report_versions_report_id_version_no")
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_report_versions_workspace_id_id")),
    )
    op.create_table(
        "reporting_obligations",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.Enum("required", "excused", name="obligation_state"), nullable=False),
        sa.Column("excuse_reason", sa.Text(), nullable=True),
        sa.Column("extension_until_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "membership_id"],
            ["project_memberships.workspace_id", "project_memberships.id"],
            name=op.f("fk_reporting_obligations_workspace_id_membership_id_project_memberships"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            name=op.f("fk_reporting_obligations_workspace_id_period_id_reporting_periods"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_reporting_obligations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reporting_obligations")),
        sa.UniqueConstraint(
            "membership_id",
            "period_id",
            name=op.f("uq_reporting_obligations_membership_id_period_id"),
        ),
    )
    op.create_index(
        "ix_reporting_obligations_period_id_state",
        "reporting_obligations",
        ["period_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_reporting_obligations_student_id", "reporting_obligations", ["student_id"], unique=False
    )
    op.create_table(
        "revision_requests",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("report_version_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("resolved_in_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "report_id"],
            ["weekly_reports.workspace_id", "weekly_reports.id"],
            name=op.f("fk_revision_requests_workspace_id_report_id_weekly_reports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_revision_requests_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revision_requests")),
    )
    op.create_index(
        "ix_revision_requests_report_id", "revision_requests", ["report_id"], unique=False
    )
    op.create_table(
        "project_report_entries",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("report_version_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column(
            "milestone_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
        sa.Column("planned_work_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("work_performed", sa.Text(), nullable=False),
        sa.Column("results", sa.Text(), nullable=False),
        sa.Column("experiments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deviations", sa.Text(), nullable=False),
        sa.Column("next_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("questions", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hours", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("content_changed_in_version_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_project_report_entries_workspace_id_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "report_version_id"],
            ["report_versions.workspace_id", "report_versions.id"],
            name=op.f("fk_project_report_entries_workspace_id_report_version_id_report_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_project_report_entries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_report_entries")),
        sa.UniqueConstraint(
            "report_version_id",
            "project_id",
            name=op.f("uq_project_report_entries_report_version_id_project_id"),
        ),
    )
    op.create_index(
        "ix_project_report_entries_project_id",
        "project_report_entries",
        ["project_id"],
        unique=False,
    )

    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION raise_immutable()"
        )
    op.execute(FIRST_SUBMITTED_AT_IS_WRITE_ONCE)
    op.execute(
        "CREATE TRIGGER trg_freeze_first_submitted_at BEFORE UPDATE ON weekly_reports "
        "FOR EACH ROW EXECUTE FUNCTION freeze_first_submitted_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_freeze_first_submitted_at ON weekly_reports")
    op.execute("DROP FUNCTION IF EXISTS freeze_first_submitted_at()")
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_immutable ON {table}")
    op.drop_index("ix_project_report_entries_project_id", table_name="project_report_entries")
    op.drop_table("project_report_entries")
    op.drop_index("ix_revision_requests_report_id", table_name="revision_requests")
    op.drop_table("revision_requests")
    op.drop_index("ix_reporting_obligations_student_id", table_name="reporting_obligations")
    op.drop_index("ix_reporting_obligations_period_id_state", table_name="reporting_obligations")
    op.drop_table("reporting_obligations")
    op.drop_table("report_versions")
    op.drop_index("ix_weekly_reports_period_id_workflow_state", table_name="weekly_reports")
    op.drop_table("weekly_reports")
    op.drop_index("ix_reporting_periods_workspace_id_deadline_utc", table_name="reporting_periods")
    op.drop_table("reporting_periods")
    op.drop_index("ix_calendar_configs_workspace_id_effective_from", table_name="calendar_configs")
    op.drop_table("calendar_configs")
    for enum_name in ("timing_status", "report_state", "obligation_state"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
