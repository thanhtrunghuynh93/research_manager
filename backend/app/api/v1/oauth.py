"""The consent step of connecting a connector (ADR 0025).

Cookie-authenticated like the rest of /api/v1: the professor is already signed in to the app, and
the SPA's /connect page asks them here before any code is minted. The OAuth protocol endpoints
themselves are in app.api.oauth.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ProfScopeDep, SessionDep
from app.identity import service as identity_service
from app.oauth import service
from app.oauth.schemas import AuthorizeIn, AuthorizeOut, ConsentOut

router = APIRouter(prefix="/oauth", tags=["oauth"])


async def _validated(session: SessionDep, payload: AuthorizeIn) -> service.AuthorizeRequest:
    return await service.validate_authorize_request(
        session,
        client_id=payload.client_id,
        redirect_uri=payload.redirect_uri,
        response_type=payload.response_type,
        code_challenge=payload.code_challenge,
        code_challenge_method=payload.code_challenge_method,
        scope=payload.scope,
        resource=payload.resource,
        state=payload.state,
    )


@router.post("/consent", summary="What a connector is asking for, before the professor decides")
async def consent(payload: AuthorizeIn, scope: ProfScopeDep, session: SessionDep) -> ConsentOut:
    request = await _validated(session, payload)
    workspace = await identity_service.get_workspace(session, scope, scope.workspace_id)
    return ConsentOut(
        client_name=request.client.client_name, scope=request.scope, workspace_name=workspace.name
    )


@router.post("/authorize", summary="Allow the connector to read this workspace")
async def authorize(payload: AuthorizeIn, scope: ProfScopeDep, session: SessionDep) -> AuthorizeOut:
    request = await _validated(session, payload)
    code = await service.issue_code(session, scope, request)
    return AuthorizeOut(redirect_to=service.redirect_with(request, code=code))


@router.post("/deny", summary="Refuse the connector")
async def deny(payload: AuthorizeIn, scope: ProfScopeDep, session: SessionDep) -> AuthorizeOut:
    request = await _validated(session, payload)
    return AuthorizeOut(redirect_to=service.redirect_with(request, error="access_denied"))
