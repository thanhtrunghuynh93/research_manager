"""projects: a student may start a project and join one the professor has opened

PROJ-07 and AUTH-07. Two columns, each carrying one decision.

`projects.open_to_join` is the gate. A membership is the entire grant of access to a project's
records — its plan, milestones, tasks, decisions and the names of everyone who has worked on it —
so letting a student join any project at will would make the member list a roster of the whole
workspace. The flag makes that a decision the professor takes per project. It defaults to false,
which means no existing project changes visibility when this migration runs.

`project_memberships.origin` records how the row came about. It is read by the obligation
derivation: a professor assigning someone mid-week means that week is owed, because the professor
knows what they are asking for; a student joining mid-week does not owe the week that is already
ending. Existing rows were all written by a professor, so `assigned` is the correct backfill.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORIGIN = sa.Enum("assigned", "self_joined", name="membership_origin")


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("open_to_join", sa.Boolean(), nullable=False, server_default="false"),
    )
    ORIGIN.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "project_memberships",
        sa.Column("origin", ORIGIN, nullable=False, server_default="assigned"),
    )


def downgrade() -> None:
    op.drop_column("project_memberships", "origin")
    ORIGIN.drop(op.get_bind(), checkfirst=True)
    op.drop_column("projects", "open_to_join")
