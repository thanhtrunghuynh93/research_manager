"""notifications: a period can hold more than one message of the same kind

REP-05, UI-07.

`uq_notification` was (recipient, period, kind), which made every notification of a kind after the
first in a week a silent no-op. That is right for a reminder and wrong for a revision request: a
second request, on another project or after an insufficient fix, is a second thing to tell the
student — and it is a kind they are not allowed to mute. The subject discriminates them, while a
redelivered job for the same subject is still a no-op.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-12 16:55:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_notification", table_name="notifications")
    op.create_index(
        "uq_notification",
        "notifications",
        ["recipient_id", "period_id", "kind", "subject_id"],
        unique=True,
        postgresql_where=sa.text("period_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_notification", table_name="notifications")
    op.create_index(
        "uq_notification",
        "notifications",
        ["recipient_id", "period_id", "kind"],
        unique=True,
        postgresql_where=sa.text("period_id IS NOT NULL"),
    )
