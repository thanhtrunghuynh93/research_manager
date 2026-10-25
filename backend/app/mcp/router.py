"""The /mcp endpoint: bearer-authenticated JSON-RPC over POST (ADR 0025)."""

from __future__ import annotations

from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from app.api.deps import SessionDep, SettingsDep
from app.mcp import server
from app.oauth import service as oauth_service

router = APIRouter(tags=["mcp"])


def _unauthorized(base: str, description: str) -> Response:
    """401 with the pointer a client follows to discover where to sign in (RFC 9728)."""
    challenge = (
        f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource", '
        f'error="invalid_token", error_description="{description}"'
    )
    return Response(status_code=401, headers={"WWW-Authenticate": challenge})


@router.api_route("/mcp", methods=["GET", "DELETE"], include_in_schema=False)
async def not_streamable() -> Response:
    # No server-initiated stream and no session to end; the specification allows 405 for both.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp", include_in_schema=False)
async def mcp(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    base = settings.public_url.rstrip("/")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return _unauthorized(base, "a bearer token is required")
    context = await oauth_service.resolve_access_token(session, token=token.strip())
    if context is None:
        return _unauthorized(base, "the token is unknown, expired or revoked")

    try:
        payload: Any = orjson.loads(await request.body())
    except orjson.JSONDecodeError:
        return JSONResponse(server.error_response(None, server.PARSE_ERROR, "invalid JSON"), 400)

    messages = payload if isinstance(payload, list) else [payload]
    replies = []
    for message in messages:
        reply = await server.handle_message(
            session, context.scope, message, token_id=context.token_id
        )
        if reply is not None:
            replies.append(reply)
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(payload, list) else replies[0])
