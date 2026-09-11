"""AUTH-01 over HTTP: login, the session cookie, acceptance, and recovery."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models, service
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module

SESSION_COOKIE = "rm_session"
NEW_PASSWORD = "a brand new long password"  # noqa: S105 - test credential


async def test_login_sets_an_httponly_session_cookie(
    client: AsyncClient, student_a: models.User
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["email"] == student_a.email
    assert "password_hash" not in response.text
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()  # the attribute value is case-insensitive


async def test_the_cookie_authenticates_the_next_request(
    client: AsyncClient, student_a: models.User
) -> None:
    await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": DEFAULT_PASSWORD}
    )

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == str(student_a.id)


async def test_me_without_a_cookie_is_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_a_wrong_password_is_401_and_names_neither_field(
    client: AsyncClient, student_a: models.User
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": "not the password"}
    )

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert student_a.email not in response.text


async def test_logout_clears_the_cookie_and_the_session(
    client: AsyncClient, student_a: models.User
) -> None:
    await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": DEFAULT_PASSWORD}
    )

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_a_revoked_session_stops_working_immediately(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: models.User
) -> None:
    # AUTH-03: deactivation invalidates subsequent access, not just new logins.
    await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": DEFAULT_PASSWORD}
    )
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    await service.deactivate_user(db, prof_scope, student_a.id)

    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_accepting_an_invitation_activates_and_signs_in(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope
) -> None:
    invited = await service.invite_user(db, prof_scope, email="new@example.edu")

    response = await client.post(
        "/api/v1/auth/accept-invitation",
        json={"token": invited.token, "password": NEW_PASSWORD, "display_name": "New Student"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "active"
    assert (await client.get("/api/v1/auth/me")).json()["display_name"] == "New Student"


async def test_an_invalid_invitation_token_is_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/accept-invitation", json={"token": "nope", "password": NEW_PASSWORD}
    )

    assert response.status_code == 422


async def test_requesting_a_reset_always_answers_the_same(
    client: AsyncClient, student_a: models.User
) -> None:
    known = await client.post("/api/v1/auth/password-reset", json={"email": student_a.email})
    unknown = await client.post("/api/v1/auth/password-reset", json={"email": "nobody@example.edu"})

    assert known.status_code == unknown.status_code == 202
    assert known.text == unknown.text, "the response must not reveal whether the account exists"


async def test_confirming_a_reset_changes_the_password(
    client: AsyncClient, db: AsyncSession, student_a: models.User
) -> None:
    requested = await service.request_password_reset(db, email=student_a.email)
    assert requested is not None

    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": requested.token, "password": NEW_PASSWORD},
    )

    assert response.status_code == 204
    signed_in = await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": NEW_PASSWORD}
    )
    assert signed_in.status_code == 200


async def test_the_session_token_never_appears_in_a_response_body(
    client: AsyncClient, student_a: models.User
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": student_a.email, "password": DEFAULT_PASSWORD}
    )

    token = client.cookies[SESSION_COOKIE]
    assert token not in response.text
