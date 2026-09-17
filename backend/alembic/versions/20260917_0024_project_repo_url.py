"""projects: where the code lives, as a link

PROJ-01 lists shared resources among a project's record, and the one every project has is the
repository. It was reachable only as a free-form key inside `shared_resources`, which no screen
read and no form wrote, so in practice a project did not say where its code was.

This is a link and nothing more. It is not `repositories` (REPO-01): that is a connection with a
provider, an external id and a credential, it pulls events and attributes contributions to
students, and only a professor may set one up. Filling this column in attributes nothing to
anybody — it is there so a person can find the code.

Nullable with no default: optional means absent, not "".

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("repo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "repo_url")
