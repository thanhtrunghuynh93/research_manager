"""Every refusal this API makes is one problem document, whatever raised it.

The shape is the contract the browser client relies on: `detail` is a string, and a client that
renders it renders a sentence. FastAPI's own validation failures were the one exception — an array
of `{loc, msg, type, input, ctx}` objects under the same key — and rendering that array put React
error #31 on the screen in place of the whole application (QA pass 3, defect #1).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.identity import models as identity_models
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module


async def _sign_in(client: AsyncClient, user: identity_models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def test_a_malformed_identifier_in_the_path_is_a_problem_document(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.get("/api/v1/periods/not-a-uuid/report")

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str)
    assert body["title"] == "Validation failed"
    assert body["detail"].startswith("period_id:")


async def test_a_rejected_field_names_itself_in_the_detail(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.post(
        "/api/v1/projects", json={"title": "Mine", "stage": "theory", "repo_url": 17}
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str)
    assert "repo_url" in body["detail"]


async def test_a_nested_field_is_named_the_way_it_was_sent(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """`("body", "entries", 0, "hours")` reads as `entries[0].hours`, not as a tuple."""
    # The body is validated before the endpoint runs, so the period need not exist for the
    # rejection under test to be the one that happens.
    await _sign_in(client, student_a)

    response = await client.post(
        "/api/v1/periods/01a0ad80-2559-76f0-a6e9-d333a57947d1/report/submit",
        json={"entries": [{"project_id": str(student_a.id), "stage": "theory", "hours": -5}]},
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str)
    assert "entries[0].hours" in body["detail"]


async def test_the_rejected_value_is_not_echoed_back(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """`input` is the caller's own payload. Repeating it puts it in every log and proxy between
    here and the browser, and the field name already says where to look."""
    await _sign_in(client, student_a)
    secret = "correct-horse-battery-staple"

    response = await client.post(
        "/api/v1/projects", json={"title": "Mine", "stage": "theory", "repo_url": secret}
    )

    assert response.status_code == 422
    assert secret not in response.text


async def test_the_field_errors_travel_beside_the_sentence(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    # A form that wants to mark the offending input still can; it reads the extra key rather than
    # parsing the sentence.
    await _sign_in(client, student_a)

    response = await client.post("/api/v1/projects", json={"stage": "theory"})

    assert response.status_code == 422
    fields = response.json()["invalid_fields"]
    assert {entry["field"] for entry in fields} == {"title"}
    assert all(isinstance(entry["message"], str) for entry in fields)


async def test_a_domain_refusal_still_reads_the_same_way(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    # The handler added for FastAPI's validation errors must not have changed the shape of the
    # refusals the services raise themselves.
    await _sign_in(client, student_a)

    response = await client.post(
        "/api/v1/projects",
        json={"title": "Mine", "stage": "theory", "repo_url": "github.com/lab/mine"},
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str)
    assert body["type"] == "about:blank"


async def test_several_failures_are_counted_rather_than_listed(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    # Naming only the first sends a caller who fixes it straight back here for the second.
    await _sign_in(client, student_a)

    response = await client.post("/api/v1/projects", json={})

    assert response.status_code == 422
    body = response.json()
    assert len(body["invalid_fields"]) > 1
    assert body["detail"].endswith(f"(and {len(body['invalid_fields']) - 1} more)")
