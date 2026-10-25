"""OAuth 2.1 protocol endpoints and discovery documents for the MCP connector (ADR 0025).

Unauthenticated by nature: a client has no session. Bodies follow RFC 6749/7591/7009/8414/9728, not
this API's problem+json, because connectors parse those shapes.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.api.deps import SessionDep, SettingsDep
from app.oauth import service
from app.oauth.schemas import ClientRegistrationIn, ClientRegistrationOut, TokenOut

router = APIRouter(tags=["oauth"])

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _error(exc: service.OAuthError) -> JSONResponse:
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    return JSONResponse(body, status_code=exc.status_code, headers=NO_STORE)


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
async def protected_resource(settings: SettingsDep) -> dict[str, object]:
    base = settings.public_url.rstrip("/")
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "scopes_supported": list(service.SUPPORTED_SCOPES),
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def authorization_server(settings: SettingsDep) -> dict[str, object]:
    base = settings.public_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": list(service.SUPPORTED_SCOPES),
    }


@router.post("/oauth/register", status_code=201, include_in_schema=False)
async def register(payload: ClientRegistrationIn, session: SessionDep) -> Response:
    try:
        client = await service.register_client(
            session, client_name=payload.client_name, redirect_uris=payload.redirect_uris
        )
    except service.OAuthError as exc:
        return _error(exc)
    out = ClientRegistrationOut(
        client_id=client.client_id,
        client_name=client.client_name,
        redirect_uris=list(client.redirect_uris),
    )
    return JSONResponse(out.model_dump(), status_code=201, headers=NO_STORE)


@router.get("/oauth/authorize", include_in_schema=False)
async def authorize(
    session: SessionDep,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "",
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    scope: str | None = None,
    resource: str | None = None,
    state: str | None = None,
) -> Response:
    """Validate, then hand the browser to the SPA's consent page with the same query string."""
    try:
        request = await service.validate_authorize_request(
            session,
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            resource=resource,
            state=state,
        )
    except service.OAuthError as exc:
        # An unregistered redirect URI gets no redirect: this page is the end of the road.
        return _error(exc)
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": response_type,
        "code_challenge": request.code_challenge,
        "code_challenge_method": "S256",
        "scope": request.scope,
    }
    if resource:
        query["resource"] = resource
    if state:
        query["state"] = state
    return RedirectResponse(f"/connect?{urlencode(query)}", status_code=302, headers=NO_STORE)


@router.post("/oauth/token", include_in_schema=False)
async def token(
    session: SessionDep,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        if grant_type == "authorization_code":
            if not (code and redirect_uri and code_verifier):
                raise service.OAuthError("invalid_request", "code, redirect_uri and code_verifier")
            grant = await service.exchange_code(
                session,
                client_id=client_id,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise service.OAuthError("invalid_request", "refresh_token is required")
            grant = await service.refresh(session, client_id=client_id, refresh_token=refresh_token)
        else:
            raise service.OAuthError("unsupported_grant_type", grant_type)
    except service.OAuthError as exc:
        return _error(exc)
    out = TokenOut(
        access_token=grant.access_token,
        expires_in=grant.expires_in,
        refresh_token=grant.refresh_token,
        scope=grant.scope,
    )
    return JSONResponse(out.model_dump(), headers=NO_STORE)


@router.post("/oauth/revoke", include_in_schema=False)
async def revoke(session: SessionDep, token: Annotated[str, Form()]) -> Response:
    await service.revoke(session, token=token)
    return Response(status_code=200, headers=NO_STORE)
