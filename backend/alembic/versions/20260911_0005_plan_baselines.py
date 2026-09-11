"""plan_baselines: the frozen weekly plan a week is assessed against

Requirements PROJ-04, ASSESS-05, AC-18; architecture section 5.5.

Revision ID: f3479a5f54bc
Revises: 0004
Create Date: 2026-09-11 18:02:00.371318+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# PROJ-04: the committed content of a baseline cannot change. The only edits a row accepts are the
# two state moves in architecture section 5.5 — a proposal the professor accepts, and a version a
# later one supersedes — so the commitments originally missed can never be edited away.
PLAN_BASELINE_GUARD = """
CREATE OR REPLACE FUNCTION guard_plan_baseline() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'plan_baselines rows are immutable: DELETE not allowed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.membership_id IS DISTINCT FROM OLD.membership_id
       OR NEW.period_id IS DISTINCT FROM OLD.period_id
       OR NEW.version_no IS DISTINCT FROM OLD.version_no
       OR NEW.frozen_at IS DISTINCT FROM OLD.frozen_at
       OR NEW.source_entry_id IS DISTINCT FROM OLD.source_entry_id
       OR NEW.supersedes_id IS DISTINCT FROM OLD.supersedes_id
       OR NEW.change_reason IS DISTINCT FROM OLD.change_reason
       OR NEW.proposed_by IS DISTINCT FROM OLD.proposed_by THEN
        RAISE EXCEPTION 'a frozen plan is immutable: only its state may change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF NEW.state = 'superseded' THEN
        RETURN NEW;
    END IF;
    IF OLD.state = 'proposed' AND NEW.state = 'accepted' THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'a frozen plan is immutable: % -> % is not allowed', OLD.state, NEW.state
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "plan_baselines",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("period_id", sa.UUID(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("frozen", "empty", "proposed", "accepted", "superseded", name="baseline_state"),
            nullable=False,
        ),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_entry_id", sa.UUID(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("proposed_by", sa.UUID(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_plan_baselines_workspace_id_membership_id_project_memberships"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "period_id"],
            ["reporting_periods.workspace_id", "reporting_periods.id"],
            name=op.f("fk_plan_baselines_workspace_id_period_id_reporting_periods"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_plan_baselines_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_baselines")),
        sa.UniqueConstraint(
            "membership_id",
            "period_id",
            "version_no",
            name=op.f("uq_plan_baselines_membership_id_period_id_version_no"),
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_plan_baselines_workspace_id_id")),
    )
    op.create_index("ix_plan_baselines_period_id", "plan_baselines", ["period_id"], unique=False)
    op.create_index(
        "uq_baseline_in_effect",
        "plan_baselines",
        ["membership_id", "period_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('frozen', 'accepted')"),
    )
    op.create_table(
        "plan_baseline_items",
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("baseline_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("planned_outcome", sa.Text(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "baseline_id"],
            ["plan_baselines.workspace_id", "plan_baselines.id"],
            name=op.f("fk_plan_baseline_items_workspace_id_baseline_id_plan_baselines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_plan_baseline_items_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_baseline_items")),
    )
    op.create_index(
        "ix_plan_baseline_items_baseline_id", "plan_baseline_items", ["baseline_id"], unique=False
    )

    op.execute(PLAN_BASELINE_GUARD)
    op.execute(
        "CREATE TRIGGER trg_guard_plan_baseline BEFORE UPDATE OR DELETE ON plan_baselines "
        "FOR EACH ROW EXECUTE FUNCTION guard_plan_baseline()"
    )
    op.execute(
        "CREATE TRIGGER trg_immutable BEFORE UPDATE OR DELETE ON plan_baseline_items "
        "FOR EACH ROW EXECUTE FUNCTION raise_immutable()"
    )

    # The reporting module now exists, so the membership bounds can point at real periods (REP-01).
    op.create_foreign_key(
        "fk_memberships_first_required_period",
        "project_memberships",
        "reporting_periods",
        ["workspace_id", "first_required_period_id"],
        ["workspace_id", "id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_memberships_last_required_period",
        "project_memberships",
        "reporting_periods",
        ["workspace_id", "last_required_period_id"],
        ["workspace_id", "id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_memberships_last_required_period", "project_memberships", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_memberships_first_required_period", "project_memberships", type_="foreignkey"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_immutable ON plan_baseline_items")
    op.execute("DROP TRIGGER IF EXISTS trg_guard_plan_baseline ON plan_baselines")
    op.execute("DROP FUNCTION IF EXISTS guard_plan_baseline()")
    op.drop_index("ix_plan_baseline_items_baseline_id", table_name="plan_baseline_items")
    op.drop_table("plan_baseline_items")
    op.drop_index(
        "uq_baseline_in_effect",
        table_name="plan_baselines",
        postgresql_where=sa.text("state IN ('frozen', 'accepted')"),
    )
    op.drop_index("ix_plan_baselines_period_id", table_name="plan_baselines")
    op.drop_table("plan_baselines")
    op.execute("DROP TYPE IF EXISTS baseline_state")
