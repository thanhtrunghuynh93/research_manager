"""FastAPI dependencies shared by routers.

The session cookie is the only credential the API accepts: an opaque token whose digest identifies
a row in `sessions` (architecture §6.2). Every scoped endpoint resolves it into a Scope, and every
repository read then compiles that Scope into a SQL predicate (AUTH-02).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.errors import UnauthenticatedError
from app.identity import service as identity_service

SessionDep = Annotated[AsyncSession, Depends(get_session)]

SESSION_COOKIE = "rm_session"  # noqa: S105 - cookie name, not a secret


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """SameSite=Lax keeps the cookie off cross-site form posts; Secure follows the deployment."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.env == "prod",
        samesite="lax",
        path="/",
        max_age=int(identity_service.security.SESSION_ABSOLUTE_TTL.total_seconds()),
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=settings.env == "prod", samesite="lax", path="/"
    )


async def current_context(
    request: Request, session: SessionDep
) -> identity_service.AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise UnauthenticatedError("no session")
    context = await identity_service.resolve_session(session, token=token)
    if context is None:
        raise UnauthenticatedError("session expired or revoked")
    return context


ContextDep = Annotated[identity_service.AuthContext, Depends(current_context)]


async def resolve_scope(context: ContextDep) -> Scope:
    return context.scope


ScopeDep = Annotated[Scope, Depends(resolve_scope)]


async def prof_scope(scope: ScopeDep) -> Scope:
    scope.require_prof()
    return scope


ProfScopeDep = Annotated[Scope, Depends(prof_scope)]


def settings_dep(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


def idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> str | None:
    """Clients send Idempotency-Key on retryable mutations (report submission, review actions)."""
    return key


IdempotencyKeyDep = Annotated[str | None, Depends(idempotency_key)]
