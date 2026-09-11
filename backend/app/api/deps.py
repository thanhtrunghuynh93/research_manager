"""FastAPI dependencies shared by routers.

resolve_scope() is completed by the identity module (sessions → Scope). Until then any
endpoint that requires a scope returns 401, which is the safe default.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.db import get_session
from app.core.errors import UnauthenticatedError

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def resolve_scope(session: SessionDep) -> Scope:
    raise UnauthenticatedError("no session")


ScopeDep = Annotated[Scope, Depends(resolve_scope)]


async def prof_scope(scope: ScopeDep) -> Scope:
    scope.require_prof()
    return scope


ProfScopeDep = Annotated[Scope, Depends(prof_scope)]


def idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> str | None:
    """Clients send Idempotency-Key on retryable mutations (report submission, review actions)."""
    return key


IdempotencyKeyDep = Annotated[str | None, Depends(idempotency_key)]
