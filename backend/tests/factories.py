"""Async row builders used by module, authz, and API tests.

Plain functions rather than factory_boy classes: the ORM is async, and a test reads better when the
row it depends on is built by one awaited call with explicit fields.
"""

from __future__ import annotations

import itertools

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import Role
from app.identity import models, security

_counter = itertools.count(1)

DEFAULT_PASSWORD = "correct horse battery staple"  # noqa: S105 - fixture credential


async def make_workspace(
    session: AsyncSession,
    *,
    name: str = "Research Lab",
    timezone: str = "Asia/Ho_Chi_Minh",
) -> models.Workspace:
    workspace = models.Workspace(name=name, timezone=timezone)
    session.add(workspace)
    await session.flush()
    return workspace


async def make_user(
    session: AsyncSession,
    workspace: models.Workspace,
    *,
    role: Role = Role.STUDENT,
    email: str | None = None,
    display_name: str | None = None,
    state: models.UserState = models.UserState.ACTIVE,
    password: str | None = DEFAULT_PASSWORD,
) -> models.User:
    address = security.normalize_email(email or f"user{next(_counter)}@example.edu")
    user = models.User(
        workspace_id=workspace.id,
        role=role,
        email=address,
        display_name=display_name or address.split("@")[0],
        password_hash=security.hash_password(password) if password else None,
        state=state,
    )
    session.add(user)
    await session.flush()
    # Belonging is a membership row, not the column (ADR 0015). The service writes one whenever it
    # creates an account; a factory that skipped it would build users nobody is on the roll of.
    session.add(models.WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await session.flush()
    return user
