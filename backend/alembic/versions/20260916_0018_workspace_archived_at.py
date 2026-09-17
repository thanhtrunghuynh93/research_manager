"""identity: workspaces can be archived

A professor who administers workspaces needs a way to close one. Deleting is not that way: every
foreign key into a workspace cascades, so a delete would take its users, projects, reports and
assessments with it and no audit row would survive to say what happened. Archiving keeps the
record and the history; `archive_workspace` refuses while any account there is still active, so
the flag never has to be enforced against live work.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "archived_at")
