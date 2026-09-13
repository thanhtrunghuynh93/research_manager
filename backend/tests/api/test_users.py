"""AUTH-01/AUTH-02 over HTTP: the user directory obeys the same predicate as the service."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.identity import models
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module


async def _sign_in(client: AsyncClient, user: models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def test_the_professor_lists_the_workspace(
    client: AsyncClient, prof: models.User, student_a: models.User, student_b: models.User
) -> None:
    await _sign_in(client, prof)

    response = await client.get("/api/v1/users")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert {str(student_a.id), str(student_b.id)} <= ids


async def test_a_student_lists_only_themselves(
    client: AsyncClient, student_a: models.User, student_b: models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.get("/api/v1/users")

    assert [item["id"] for item in response.json()["items"]] == [str(student_a.id)]


async def test_a_student_cannot_read_another_student(
    client: AsyncClient, student_a: models.User, student_b: models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.get(f"/api/v1/users/{student_b.id}")

    assert response.status_code == 404, "a hidden record is absent, not forbidden"


async def test_a_student_cannot_invite(client: AsyncClient, student_a: models.User) -> None:
    await _sign_in(client, student_a)

    response = await client.post("/api/v1/users/invitations", json={"email": "new@example.edu"})

    assert response.status_code == 403


async def test_the_professor_invites_and_the_token_stays_out_of_the_response(
    client: AsyncClient, prof: models.User
) -> None:
    await _sign_in(client, prof)

    response = await client.post(
        "/api/v1/users/invitations",
        json={"email": "New@Example.edu", "display_name": "New Student"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.edu"
    assert "token" not in body, "only the addressee of the email learns the token"


async def test_a_student_cannot_deactivate_anyone(
    client: AsyncClient, student_a: models.User, student_b: models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.post(f"/api/v1/users/{student_b.id}/deactivate")

    assert response.status_code == 403


async def test_the_professor_deactivates_and_reactivates(
    client: AsyncClient, prof: models.User, student_a: models.User
) -> None:
    await _sign_in(client, prof)

    deactivated = await client.post(f"/api/v1/users/{student_a.id}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["state"] == "deactivated"

    reactivated = await client.post(f"/api/v1/users/{student_a.id}/reactivate")
    assert reactivated.json()["state"] == "active"


async def test_a_user_edits_their_own_profile(client: AsyncClient, student_a: models.User) -> None:
    await _sign_in(client, student_a)

    response = await client.patch(
        "/api/v1/users/me", json={"display_name": "Renamed", "locale": "vi"}
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    assert response.json()["locale"] == "vi"


async def test_only_the_professor_changes_a_role(
    client: AsyncClient, student_a: models.User, student_b: models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.patch(f"/api/v1/users/{student_b.id}/role", json={"role": "prof"})

    assert response.status_code == 403


async def test_listing_users_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users")).status_code == 401


# ---------------------------------------------------------------- malformed client input
#
# A cursor is opaque to the client, so a wrong one is ordinary. `decoded["after"]` raised KeyError
# and `UUID(...)` raised ValueError, and both reached the catch-all handler as a 500 with a logged
# stack trace for what is simply a bad request.


@pytest.mark.parametrize(
    ("cursor", "why"),
    [
        ("eyJuIjoxfQ==", "valid base64 and JSON, but no `after` key"),
        ("eyJhZnRlciI6ICJub3QtYS11dWlkIn0=", "`after` is not a UUID"),
        ("not-base64-at-all!!", "not decodable at all"),
    ],
)
async def test_a_malformed_cursor_is_a_bad_request(
    client: AsyncClient, prof: models.User, cursor: str, why: str
) -> None:
    await _sign_in(client, prof)

    response = await client.get("/api/v1/users", params={"cursor": cursor})

    assert response.status_code == 422, f"{why}: {response.text}"
    assert response.json()["detail"] == "invalid cursor"


async def test_a_valid_cursor_still_pages(
    client: AsyncClient, prof: models.User, student_a: models.User, student_b: models.User
) -> None:
    await _sign_in(client, prof)

    first = (await client.get("/api/v1/users", params={"limit": 1})).json()
    assert first["next_cursor"]

    second = (
        await client.get("/api/v1/users", params={"limit": 1, "cursor": first["next_cursor"]})
    ).json()

    assert second["items"]
    assert second["items"][0]["id"] != first["items"][0]["id"]
