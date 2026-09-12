"""evidence: record how long a rate-limited sync was asked to wait

REPO-05; architecture §8.3.

The connector parses `Retry-After` and the run recorded nothing of it, so the wait the provider
asked for was discarded and nothing scheduled the retry. Keeping it on the run makes it visible to
an operator and lets the worker act on it.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-12 16:20:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sync_runs", sa.Column("retry_after_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_runs", "retry_after_seconds")
