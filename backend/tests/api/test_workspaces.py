"""ADR 0012 over HTTP: the routes carry the same ownership rule the service enforces."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import models, repository
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module


async def _sign_in(client: AsyncClient, user: models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def _own(db: AsyncSession, prof: models.User) -> None:
    workspace = await repository.get_workspace(db, prof.workspace_id)
    assert workspace is not None
    workspace.owner_id = prof.id
    await db.flush()


async def test_a_student_cannot_reach_any_workspace_route(
    client: AsyncClient, student_a: models.User
) -> None:
    await _sign_in(client, student_a)

    assert (await client.get("/api/v1/workspaces")).status_code == 403
    assert (await client.post("/api/v1/workspaces", json={"name": "Mine"})).status_code == 403


async def test_a_professor_creates_and_lists(client: AsyncClient, prof: models.User) -> None:
    # Captured before the create: creating joins, which moves the anchor the fixture points at.
    source = str(prof.workspace_id)
    await _sign_in(client, prof)

    created = await client.post("/api/v1/workspaces", json={"name": "Vision Lab"})
    assert created.status_code == 201
    assert created.json()["owner_id"] == str(prof.id)

    listed = await client.get("/api/v1/workspaces")
    assert listed.status_code == 200
    # Both, because joining one does not leave the other (ADR 0015).
    assert {row["id"] for row in listed.json()} == {source, created.json()["id"]}


async def test_renaming_a_workspace_nobody_owns_is_a_404_not_a_403(
    client: AsyncClient, prof: models.User
) -> None:
    # AC-02: the status must not distinguish "exists but not yours" from "does not exist".
    await _sign_in(client, prof)

    response = await client.patch(
        f"/api/v1/workspaces/{prof.workspace_id}", json={"name": "Renamed"}
    )

    assert response.status_code == 404


async def test_archiving_your_own_workspace_says_why_you_cannot(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    await _own(db, prof)
    await _sign_in(client, prof)

    response = await client.post(f"/api/v1/workspaces/{prof.workspace_id}/archive")

    assert response.status_code == 422
    detail = response.json()["detail"]
    # Not a head count: the professor is one of the accounts and cannot remove themselves, so
    # "remove or deactivate them" would name a step no route offers.
    assert "nobody belongs to it" in detail
    # And written for the person reading it: the UI renders this text verbatim.
    assert "route" not in detail


async def test_an_invitation_names_the_workspace_it_enrols_into(
    client: AsyncClient, prof: models.User
) -> None:
    await _sign_in(client, prof)
    created = (await client.post("/api/v1/workspaces", json={"name": "Vision Lab"})).json()

    response = await client.post(
        "/api/v1/users/invitations",
        json={"email": "new@example.edu", "workspace_id": created["id"]},
    )

    assert response.status_code == 201
    # Creating joined it (ADR 0014), so the roll is that workspace's and the invitee is on it.
    listed = (await client.get("/api/v1/users")).json()["items"]
    assert "new@example.edu" in {row["email"] for row in listed}


async def test_leaving_moves_the_account_and_the_roll_changes_with_it(
    client: AsyncClient, db: AsyncSession, prof: models.User
) -> None:
    await _own(db, prof)
    source = str(prof.workspace_id)
    await _sign_in(client, prof)

    created = (await client.post("/api/v1/workspaces", json={"name": "Vision Lab"})).json()
    await client.post(
        "/api/v1/users/invitations",
        json={"email": "new@example.edu", "workspace_id": created["id"]},
    )

    # Back to the one the account came from: a real move, so the roll is that workspace's again.
    back = await client.post(f"/api/v1/workspaces/{created['id']}/leave")
    assert back.status_code == 200
    assert back.json()["id"] == source

    home = (await client.get("/api/v1/users")).json()["items"]
    assert "new@example.edu" not in {row["email"] for row in home}


async def test_the_roll_spans_every_workspace_the_professor_belongs_to(
    client: AsyncClient, db: AsyncSession, prof: models.User, student_a: models.User
) -> None:
    """ADR 0016: reads span membership, so the roll is not the workspace you happen to be in."""
    await _own(db, prof)
    source = str(prof.workspace_id)
    await _sign_in(client, prof)
    elsewhere = (await client.post("/api/v1/workspaces", json={"name": "Vision Lab"})).json()
    await client.post(
        "/api/v1/users/invitations",
        json={"email": "theirs@example.edu", "workspace_id": elsewhere["id"]},
    )
    assert (await client.post(f"/api/v1/workspaces/{source}/join")).status_code == 200

    listed = (await client.get("/api/v1/users")).json()["items"]

    # Both workspaces' people, whichever one the professor is working in.
    assert {student_a.email, "theirs@example.edu"} <= {row["email"] for row in listed}
    assert {row["workspace_id"] for row in listed} == {source, elsewhere["id"]}


async def test_leaving_a_workspace_takes_its_people_off_the_roll(
    client: AsyncClient, db: AsyncSession, prof: models.User, student_a: models.User
) -> None:
    """The span follows membership, so giving one up narrows what the professor can read."""
    await _own(db, prof)
    await _sign_in(client, prof)
    elsewhere = (await client.post("/api/v1/workspaces", json={"name": "Vision Lab"})).json()
    await client.post(
        "/api/v1/users/invitations",
        json={"email": "theirs@example.edu", "workspace_id": elsewhere["id"]},
    )
    assert "theirs@example.edu" in {
        row["email"] for row in (await client.get("/api/v1/users")).json()["items"]
    }

    # Leaving Vision Lab, not the one holding the student: leaving that would strand them, which
    # AUTH-01 refuses. The invitee is not an active account, so nobody is stranded here.
    assert (await client.post(f"/api/v1/workspaces/{elsewhere['id']}/leave")).status_code == 200

    listed = (await client.get("/api/v1/users")).json()["items"]
    assert "theirs@example.edu" not in {row["email"] for row in listed}
    assert student_a.email in {row["email"] for row in listed}


async def test_a_student_still_sees_only_themselves(
    client: AsyncClient, student_a: models.User, student_b: models.User
) -> None:
    """A student belongs to one workspace, so spanning membership changes nothing for them."""
    await _sign_in(client, student_a)

    listed = (await client.get("/api/v1/users")).json()["items"]

    assert {row["email"] for row in listed} == {student_a.email}
