"""identity, notifications: drop the locale columns

The product is English. A stored language that every screen and every template ignores is a
setting the API offered and nothing honoured, so it is removed rather than pinned to one value:
`users.locale` was writable through the profile endpoint, and `email_deliveries.locale` chose a
template folder that no longer exists.

Reversible: downgrade restores both columns with the default they always had in practice.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-13 14:10:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "locale")
    op.drop_column("email_deliveries", "locale")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.Text(), server_default="en", nullable=False),
    )
    op.add_column(
        "email_deliveries",
        sa.Column("locale", sa.Text(), server_default="en", nullable=False),
    )
