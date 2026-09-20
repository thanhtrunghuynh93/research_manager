"""projects: starting a project is its own way onto one

A third `membership_origin`. Two was not enough once starting a project and joining one stopped
behaving the same way: a student who starts a project owes a report for the week they start it,
because they are announcing work already under way, while a student who joins an existing project
owes from the following week, because joining on a Saturday should not be a report due that Sunday.

Marking the creator's row `assigned` would have produced the same derivation and said something
false — nobody assigned them — in the one column the audit trail has for telling these apart.

Adding a value to a Postgres enum cannot run inside a transaction block on older servers, and
`ALTER TYPE ... ADD VALUE IF NOT EXISTS` is idempotent, so this is safe to re-run. The downgrade
does not remove the value: Postgres has no `DROP VALUE`, and rewriting the type would mean
rewriting every row that uses it for no gain.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE membership_origin ADD VALUE IF NOT EXISTS 'created'")


def downgrade() -> None:
    # Postgres cannot drop an enum value. Rows written as 'created' stay readable, and the
    # derivation before this revision treated anything that was not 'self_joined' the same way.
    pass
