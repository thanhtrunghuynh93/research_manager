"""job queue: the procrastinate schema

The queue lives in the same database as the records, so a job is enqueued in the transaction that
writes the work it describes (ADR 0002, architecture section 12). The schema belongs to the
library: it is applied verbatim from the installed version, which uv.lock pins.

Upgrading procrastinate means adding a migration that applies the library's own migration files
(`procrastinate.schema.SchemaManager.get_migrations_path()`), not editing this one.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from procrastinate.schema import SchemaManager

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(SchemaManager.get_schema())


def downgrade() -> None:
    # The library creates its objects inside the public schema; drop what it owns by name.
    op.execute(
        """
        DO $$
        DECLARE
            statement text;
        BEGIN
            FOR statement IN
                SELECT format('DROP TABLE IF EXISTS %I CASCADE', tablename)
                FROM pg_tables
                WHERE schemaname = current_schema() AND tablename LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE statement;
            END LOOP;

            FOR statement IN
                SELECT format('DROP FUNCTION IF EXISTS %I(%s) CASCADE',
                              p.proname, pg_get_function_identity_arguments(p.oid))
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE statement;
            END LOOP;

            FOR statement IN
                SELECT format('DROP TYPE IF EXISTS %I CASCADE', t.typname)
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = current_schema() AND t.typname LIKE 'procrastinate\\_%'
            LOOP
                EXECUTE statement;
            END LOOP;
        END;
        $$;
        """
    )
