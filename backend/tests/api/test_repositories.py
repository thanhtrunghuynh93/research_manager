"""Connecting a repository through the product (REPO-01, REPO-03, REPO-05).

The evidence module was complete and unreachable: every service existed and no route did, so a
professor could not connect a repository without a Python shell. These are the routes, and what
they have to get right is who may call them — connecting a repository is a workspace-configuration
act, and mapping a developer identity is something a student may do for themselves and nobody else.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import models as identity_models
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.api


async def _login(client: AsyncClient, user: identity_models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def _connect(client: AsyncClient, *, external_id: str = "r1") -> dict[str, object]:
    response = await client.post(
        "/api/v1/repositories",
        json={
            "provider": "github",
            "external_id": external_id,
            "full_name": f"lab/{external_id}",
            "credential_ref": "998877",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_student_cannot_connect_a_repository(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _login(client, student_a)

    response = await client.post(
        "/api/v1/repositories",
        json={"provider": "github", "external_id": "r1", "full_name": "lab/r1"},
    )

    assert response.status_code == 403


async def test_the_professor_connects_a_repository_and_it_appears_in_the_list(
    client: AsyncClient, prof: identity_models.User
) -> None:
    await _login(client, prof)

    connected = await _connect(client)
    listed = (await client.get("/api/v1/repositories")).json()

    assert connected["full_name"] == "lab/r1"
    assert connected["connection_state"] == "connected"
    assert [row["id"] for row in listed] == [connected["id"]]


async def test_a_repository_carries_its_sync_state_rather_than_nothing(
    client: AsyncClient, prof: identity_models.User
) -> None:
    """REPO-05: the screen shows last successful sync, covered range, and errors."""
    await _login(client, prof)
    connected = await _connect(client)

    status = await client.get(f"/api/v1/repositories/{connected['id']}/sync")

    assert status.status_code == 200
    # Never synced is a state, not an absence — the field exists and says so.
    assert status.json()["last_run"] is None


async def test_the_professor_can_trigger_a_sync_and_see_the_run(
    client: AsyncClient, prof: identity_models.User
) -> None:
    await _login(client, prof)
    connected = await _connect(client)

    run = await client.post(f"/api/v1/repositories/{connected['id']}/sync")

    assert run.status_code == 202, run.text
    assert run.json()["state"] in ("completed", "partial", "failed")


async def test_a_student_may_claim_their_own_developer_identity(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """REPO-03: a student links their own account; only the professor maps someone else's."""
    await _login(client, student_a)

    response = await client.post(
        "/api/v1/developer-identities",
        json={"provider": "github", "login": "student-a-gh"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["student_id"] == str(student_a.id)


async def test_a_student_cannot_claim_another_students_identity(
    client: AsyncClient, student_a: identity_models.User, student_b: identity_models.User
) -> None:
    await _login(client, student_a)

    response = await client.post(
        "/api/v1/developer-identities",
        json={"provider": "github", "login": "someone-else", "student_id": str(student_b.id)},
    )

    assert response.status_code == 403


async def test_a_student_sees_the_contributions_attributed_to_them(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """REPO-04: a student can see what was attributed to them, so it can be challenged."""
    await _login(client, student_a)

    response = await client.get("/api/v1/contributions")

    assert response.status_code == 200
    assert response.json() == []


async def test_evidence_search_is_reachable_and_scoped(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """QA-02/AUTH-02: the same predicate as everywhere else, through an ordinary endpoint."""
    await _login(client, student_a)

    response = await client.get("/api/v1/evidence/search?q=baseline")

    assert response.status_code == 200
    assert response.json() == []


# ------------------------------------------------------------------ webhooks (REPO-05, AC-09)


async def test_an_unsigned_webhook_is_refused(client: AsyncClient) -> None:
    """The signature is the only credential this route accepts; there is no session on it."""
    response = await client.post(
        "/api/v1/webhooks/github",
        content=b'{"repository": {"id": 1}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 401


async def test_a_delivery_with_a_bad_signature_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/webhooks/github",
        content=b'{"repository": {"id": 1}}',
        headers={
            "content-type": "application/json",
            "X-GitHub-Delivery": "d1",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    )

    assert response.status_code == 401


async def test_a_correctly_signed_delivery_for_an_unknown_repository_is_accepted_and_ignored(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A delivery we cannot place is not an error for GitHub to retry; it is nothing to do."""
    from app.evidence.connectors.fake import FakeRepositoryConnector

    body = json.dumps({"repository": {"id": 999}}).encode()
    secret = FakeRepositoryConnector().webhook_secret
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "content-type": "application/json",
            "X-GitHub-Delivery": "d2",
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    body = response.json()
    # Recorded, because a delivery is evidence that something is configured somewhere; but not
    # matched, which is what tells an operator the webhook is landing nowhere.
    assert body["accepted"] is True
    assert body["matched"] is False
    assert "no connected repository" in body["detail"]
