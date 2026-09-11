"""assessment: rubrics, snapshots, analysis runs, versions, reviews, notes

Requirements ASSESS-01..10; architecture sections 5.2, 9.1 to 9.5.

Revision ID: 7f095d91e9a7
Revises: 0009
Create Date: 2026-09-11 22:55:27.857009+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("report_version_id", sa.UUID(), nullable=True),
        sa.Column("entry_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("rubric_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "partial",
                "failed",
                "delayed_budget",
                "restricted",
                name="analysis_run_state",
            ),
            nullable=False,
        ),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_analysis_runs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_analysis_runs_workspace_id_id")),
    )
    op.create_index(
        "ix_analysis_runs_subject",
        "analysis_runs",
        ["student_id", "project_id", "period_id"],
        unique=False,
    )
    op.create_table(
        "assessment_versions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("report_version_id", sa.UUID(), nullable=True),
        sa.Column("entry_id", sa.UUID(), nullable=True),
        sa.Column("baseline_id", sa.UUID(), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("rubric_version_id", sa.UUID(), nullable=True),
        sa.Column("analysis_run_id", sa.UUID(), nullable=True),
        sa.Column("ratings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("progress_index", sa.SmallInteger(), nullable=True),
        sa.Column("plan_completion", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("coverage_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("confidence_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("narrative", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("prompt_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_assessment_versions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_versions")),
        sa.UniqueConstraint(
            "student_id",
            "project_id",
            "period_id",
            "version_no",
            name=op.f("uq_assessment_versions_student_id_project_id_period_id_version_no"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_assessment_versions_workspace_id_id")
        ),
    )
    op.create_index(
        "ix_assessment_versions_subject",
        "assessment_versions",
        ["student_id", "project_id", "period_id"],
        unique=False,
    )
    op.create_table(
        "evidence_snapshots",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("integration_lag_days", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("coverage_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("access_epoch", sa.Integer(), nullable=False),
        sa.Column(
            "built_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_evidence_snapshots_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_snapshots")),
        sa.UniqueConstraint(
            "workspace_id", "id", name=op.f("uq_evidence_snapshots_workspace_id_id")
        ),
    )
    op.create_index(
        "ix_evidence_snapshots_subject",
        "evidence_snapshots",
        ["student_id", "project_id", "period_id"],
        unique=False,
    )
    op.create_table(
        "feedback",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("subject_table", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=True),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "professor_comment", "student_response", "correction_request", name="feedback_kind"
            ),
            nullable=False,
        ),
        sa.Column(
            "visibility",
            postgresql.ENUM(
                "professor_only",
                "student_private",
                "project_shared",
                name="visibility",
                create_type=False,  # created by 0009 and shared with the evidence index
            ),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("responds_to_id", sa.UUID(), nullable=True),
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
            name=op.f("fk_feedback_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index("ix_feedback_recipient", "feedback", ["recipient_id"], unique=False)
    op.create_index(
        "ix_feedback_subject", "feedback", ["subject_table", "subject_id"], unique=False
    )
    op.create_table(
        "rubric_versions",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stage_applicability", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            name=op.f("fk_rubric_versions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rubric_versions")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_rubric_versions_workspace_id_id")),
        sa.UniqueConstraint(
            "workspace_id", "version", name=op.f("uq_rubric_versions_workspace_id_version")
        ),
    )
    op.create_table(
        "supervision_notes",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("period_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
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
            name=op.f("fk_supervision_notes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supervision_notes")),
    )
    op.create_index(
        "ix_supervision_notes_subject",
        "supervision_notes",
        ["student_id", "project_id"],
        unique=False,
    )
    op.create_table(
        "assessment_reviews",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("assessment_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("draft", "approved", "superseded", "withdrawn", name="review_state"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.UUID(), nullable=True),
        sa.Column("override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "assessment_version_id"],
            ["assessment_versions.workspace_id", "assessment_versions.id"],
            name=op.f(
                "fk_assessment_reviews_workspace_id_assessment_version_id_assessment_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_assessment_reviews_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_reviews")),
    )
    op.create_index("ix_assessment_reviews_state", "assessment_reviews", ["state"], unique=False)
    op.create_index(
        "uq_one_approved",
        "assessment_reviews",
        ["assessment_version_id"],
        unique=True,
        postgresql_where=sa.text("state = 'approved'"),
    )
    op.create_table(
        "evidence_snapshot_items",
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("evidence_ref_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column(
            "integration_of_earlier_work", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"],
            ["evidence_snapshots.workspace_id", "evidence_snapshots.id"],
            name=op.f("fk_evidence_snapshot_items_workspace_id_snapshot_id_evidence_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_evidence_snapshot_items_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id", "evidence_ref_id", name=op.f("pk_evidence_snapshot_items")
        ),
    )

    # ASSESS-09: a published trend and an approved history must not change underneath anyone, so a
    # correction is a new version rather than an edit (AC-03).
    for table in ("assessment_versions", "evidence_snapshot_items"):
        op.execute(
            f"CREATE TRIGGER trg_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION raise_immutable()"
        )


def downgrade() -> None:
    for table in ("assessment_versions", "evidence_snapshot_items"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_immutable ON {table}")
    op.drop_table("evidence_snapshot_items")
    op.drop_index(
        "uq_one_approved",
        table_name="assessment_reviews",
        postgresql_where=sa.text("state = 'approved'"),
    )
    op.drop_index("ix_assessment_reviews_state", table_name="assessment_reviews")
    op.drop_table("assessment_reviews")
    op.drop_index("ix_supervision_notes_subject", table_name="supervision_notes")
    op.drop_table("supervision_notes")
    op.drop_table("rubric_versions")
    op.drop_index("ix_feedback_subject", table_name="feedback")
    op.drop_index("ix_feedback_recipient", table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_evidence_snapshots_subject", table_name="evidence_snapshots")
    op.drop_table("evidence_snapshots")
    op.drop_index("ix_assessment_versions_subject", table_name="assessment_versions")
    op.drop_table("assessment_versions")
    op.drop_index("ix_analysis_runs_subject", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    # `visibility` belongs to migration 0009 and is left alone here.
    for enum_name in ("feedback_kind", "analysis_run_state", "review_state"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
