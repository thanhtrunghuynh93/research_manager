"""assistant: a cached answer is keyed to the read-set, not to the anchor

ADR 0016 gave `Scope` a `workspace_ids` read-set, so an answer can rest on records from any
workspace the asker belongs to. Validation stayed on the anchor's `access_epoch` alone, which left
two holes: ending a membership in the *other* workspace advanced that workspace's counter and never
evicted the answer (AUTH-03, AC-11), and because the unique key carries no workspace, a row written
while working in one workspace was served while working in another at the same numeric epoch.

`epoch_fingerprint` is the digest of every (workspace, epoch) pair the read spanned. `access_epoch`
stays, because `purge_stale` sweeps on it and it is still the right key for a single workspace.

An answer cached under the old rule carries no fingerprint and cannot be re-validated under the new
one, so the cache is emptied rather than migrated. It is derived data with a twelve-hour TTL; the
next ask recomputes it.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "answer_cache",
        sa.Column("epoch_fingerprint", sa.Text(), nullable=False, server_default=""),
    )
    # Nothing here can be re-validated under the new rule, and serving it would be the disclosure
    # this column exists to prevent.
    op.execute("DELETE FROM answer_cache")


def downgrade() -> None:
    op.execute("DELETE FROM answer_cache")
    op.drop_column("answer_cache", "epoch_fingerprint")
