"""ADR 0025: the OAuth flow a connector goes through, over HTTP."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import models, service
from app.identity import repository as identity_repository
from app.oauth import service as oauth_service
from tests.factories import login

pytestmark = pytest.mark.module

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 64


def _challenge(verifier: str = VERIFIER) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def _register(client: AsyncClient) -> str:
    response = await client.post(
        "/oauth/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]}
    )
    assert response.status_code == 201
    return str(response.json()["client_id"])


def _params(client_id: str, **over: str) -> dict[str, str]:
    base = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "scope": "rms:read",
        "state": "xyz",
    }
    return {**base, **over}


async def _code(client: AsyncClient, client_id: str) -> str:
    response = await client.post("/api/v1/oauth/authorize", json=_params(client_id))
    assert response.status_code == 200, response.text
    query = parse_qs(urlsplit(response.json()["redirect_to"]).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


async def _tokens(client: AsyncClient, client_id: str, code: str, verifier: str = VERIFIER):
    return await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
        },
    )


async def test_discovery_documents_name_the_endpoints(client: AsyncClient) -> None:
    resource = (await client.get("/.well-known/oauth-protected-resource")).json()
    server = (await client.get("/.well-known/oauth-authorization-server")).json()

    assert resource["resource"].endswith("/mcp")
    assert resource["authorization_servers"] == [server["issuer"]]
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["token_endpoint"].endswith("/oauth/token")


async def test_a_redirect_uri_must_be_https_or_loopback(client: AsyncClient) -> None:
    response = await client.post(
        "/oauth/register", json={"client_name": "x", "redirect_uris": ["http://evil.example/cb"]}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_authorize_hands_the_browser_to_the_consent_page(client: AsyncClient) -> None:
    client_id = await _register(client)

    response = await client.get("/oauth/authorize", params=_params(client_id))

    assert response.status_code == 302
    assert response.headers["location"].startswith("/connect?")
    assert "code_challenge=" in response.headers["location"]


async def test_authorize_refuses_an_unregistered_redirect_without_redirecting(
    client: AsyncClient,
) -> None:
    client_id = await _register(client)

    response = await client.get(
        "/oauth/authorize", params=_params(client_id, redirect_uri="https://evil.example/cb")
    )

    assert response.status_code == 400
    assert "location" not in response.headers


async def test_authorize_requires_pkce(client: AsyncClient) -> None:
    client_id = await _register(client)

    response = await client.get(
        "/oauth/authorize", params=_params(client_id, code_challenge_method="plain")
    )

    assert response.json()["error"] == "invalid_request"


async def test_the_full_flow_gives_a_token_that_resolves_to_the_professor(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    client_id = await _register(client)
    await login(client, prof)

    consent = await client.post("/api/v1/oauth/consent", json=_params(client_id))
    assert consent.json()["client_name"] == "Claude"
    code = await _code(client, client_id)
    response = await _tokens(client, client_id, code)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    context = await oauth_service.resolve_access_token(db, token=body["access_token"])
    assert context is not None
    assert context.scope.user_id == prof.id
    assert context.scope.workspace_id == prof.workspace_id


async def test_a_student_cannot_authorise_a_connector(
    client: AsyncClient, student_a: models.User
) -> None:
    client_id = await _register(client)
    await login(client, student_a)

    response = await client.post("/api/v1/oauth/authorize", json=_params(client_id))

    assert response.status_code == 403


async def test_authorizing_needs_a_signed_in_professor(client: AsyncClient) -> None:
    client_id = await _register(client)

    response = await client.post("/api/v1/oauth/authorize", json=_params(client_id))

    assert response.status_code == 401


async def test_a_code_works_once(client: AsyncClient, prof: models.User) -> None:
    client_id = await _register(client)
    await login(client, prof)
    code = await _code(client, client_id)

    first = await _tokens(client, client_id, code)
    second = await _tokens(client, client_id, code)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


async def test_a_wrong_verifier_is_refused(client: AsyncClient, prof: models.User) -> None:
    client_id = await _register(client)
    await login(client, prof)
    code = await _code(client, client_id)

    response = await _tokens(client, client_id, code, verifier="w" * 64)

    assert response.json()["error"] == "invalid_grant"


async def test_refresh_rotates_and_a_replayed_refresh_revokes_everything(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    client_id = await _register(client)
    await login(client, prof)
    first = (await _tokens(client, client_id, await _code(client, client_id))).json()

    def refresh(token: str):
        return client.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": token},
        )

    second = (await refresh(first["refresh_token"])).json()
    assert second["access_token"] != first["access_token"]
    assert await oauth_service.resolve_access_token(db, token=first["access_token"]) is None
    assert await oauth_service.resolve_access_token(db, token=second["access_token"]) is not None

    replay = await refresh(first["refresh_token"])

    assert replay.json()["error"] == "invalid_grant"
    assert await oauth_service.resolve_access_token(db, token=second["access_token"]) is None


async def test_revoking_kills_the_token(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    client_id = await _register(client)
    await login(client, prof)
    grant = (await _tokens(client, client_id, await _code(client, client_id))).json()

    await client.post("/oauth/revoke", data={"token": grant["access_token"]})

    assert await oauth_service.resolve_access_token(db, token=grant["access_token"]) is None


async def test_a_deactivated_professor_loses_the_token(
    client: AsyncClient,
    db: AsyncSession,
    prof: models.User,
    workspace: models.Workspace,
) -> None:
    client_id = await _register(client)
    await login(client, prof)
    grant = (await _tokens(client, client_id, await _code(client, client_id))).json()
    prof.state = models.UserState.DEACTIVATED
    await db.flush()

    assert await oauth_service.resolve_access_token(db, token=grant["access_token"]) is None


async def test_a_token_keeps_its_workspace_while_the_account_works_in_another(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    """Switching labs in the app does not repoint a connector; it stays where it was consented."""
    client_id = await _register(client)
    await login(client, prof)
    grant = (await _tokens(client, client_id, await _code(client, client_id))).json()
    original = prof.workspace_id
    scope = await service.scope_for(db, prof)
    await service.create_workspace(db, scope, name="Other")  # joins it, so the account moves
    assert prof.workspace_id != original

    context = await oauth_service.resolve_access_token(db, token=grant["access_token"])

    assert context is not None
    assert context.scope.workspace_id == original


async def test_a_token_falls_back_to_the_active_workspace_after_leaving_its_own(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    client_id = await _register(client)
    await login(client, prof)
    grant = (await _tokens(client, client_id, await _code(client, client_id))).json()
    original = prof.workspace_id
    other = await service.create_workspace(db, await service.scope_for(db, prof), name="Other")
    await identity_repository.remove_membership(db, original, prof.id)

    context = await oauth_service.resolve_access_token(db, token=grant["access_token"])

    assert context is not None
    assert context.scope.workspace_id == other.id


async def test_registration_and_token_endpoints_are_rate_limited(client: AsyncClient) -> None:
    from app.api.middleware import auth_rate_limits

    window, allowed = auth_rate_limits()["/oauth/register"]
    assert window > 0
    body = {"client_name": "x", "redirect_uris": [REDIRECT]}

    for _ in range(allowed):
        assert (await client.post("/oauth/register", json=body)).status_code == 201

    assert (await client.post("/oauth/register", json=body)).status_code == 429
