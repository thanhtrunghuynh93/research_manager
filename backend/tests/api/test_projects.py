"""The project endpoints over HTTP, including the scope a membership grants a signed-in student."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.projects import service
from tests.factories import DEFAULT_PASSWORD

pytestmark = pytest.mark.module


async def _sign_in(client: AsyncClient, user: identity_models.User) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def test_the_professor_creates_a_project(
    client: AsyncClient, prof: identity_models.User
) -> None:
    await _sign_in(client, prof)

    response = await client.post(
        "/api/v1/projects",
        json={
            "title": "Baseline evaluation",
            "description": "Evaluate the published baselines.",
            "stage": "implementation",
            "research_questions": ["Does the reported gain hold?"],
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "proposed"


async def test_a_student_creates_a_project_and_it_is_active(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.post("/api/v1/projects", json={"title": "Mine", "stage": "theory"})

    assert response.status_code == 201
    assert response.json()["status"] == "active", "no second party has to activate it (PROJ-07)"

    # Readable straight afterwards, which is only true because the creator was enrolled on it.
    listed = await client.get("/api/v1/projects")
    assert [item["title"] for item in listed.json()["items"]] == ["Mine"]


async def test_the_joinable_list_is_a_narrower_read_than_the_project(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # The projection is the point: someone who has not joined has no claim on the research
    # questions or the intended contributions, and this asserts they are not served either.
    project = await service.create_project(
        db,
        prof_scope,
        title="Open",
        stage="theory",
        research_questions=["Confidential until you are on it"],
    )
    await service.update_project(db, prof_scope, project.id, status="active", open_to_join=True)
    await _sign_in(client, student_a)

    # Also the route-ordering check: `/joinable` must be declared above `/{project_id}`, or the
    # UUID path parameter claims the literal and this answers 422.
    response = await client.get("/api/v1/projects/joinable")

    assert response.status_code == 200
    assert [row["title"] for row in response.json()] == ["Open"]
    assert set(response.json()[0]) == {"id", "title", "stage", "status", "member_count"}


async def test_a_student_joins_an_open_project_over_http(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await service.create_project(db, prof_scope, title="Open", stage="theory")
    await service.update_project(db, prof_scope, project.id, status="active", open_to_join=True)
    await _sign_in(client, student_a)

    assert (await client.get(f"/api/v1/projects/{project.id}")).status_code == 404

    joined = await client.post(f"/api/v1/projects/{project.id}/join", json={})
    assert joined.status_code == 201

    assert (await client.get(f"/api/v1/projects/{project.id}")).status_code == 200
    # A project they are already on is not on offer, so joining twice is "not found" rather than a
    # conflict — the same answer as closed, archived, and elsewhere, which is what keeps this from
    # being a way to probe what exists. The conflict remains for a professor assigning twice.
    assert (await client.post(f"/api/v1/projects/{project.id}/join", json={})).status_code == 404


async def test_a_closed_project_cannot_be_joined_over_http(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await service.create_project(db, prof_scope, title="Closed", stage="theory")
    await service.update_project(db, prof_scope, project.id, status="active")
    await _sign_in(client, student_a)

    assert (await client.post(f"/api/v1/projects/{project.id}/join", json={})).status_code == 404


async def test_only_the_creator_may_patch_their_project(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    theirs = await service.create_project(db, prof_scope, title="Professor's", stage="theory")
    await service.add_member(db, prof_scope, theirs.id, student_id=student_a.id)
    await _sign_in(client, student_a)

    mine = await client.post("/api/v1/projects", json={"title": "Mine", "stage": "theory"})
    project_id = mine.json()["id"]

    assert (
        await client.patch(f"/api/v1/projects/{project_id}", json={"title": "Renamed"})
    ).status_code == 200
    # Standing, not description: the professor decides whether work is owed and who may read it.
    assert (
        await client.patch(f"/api/v1/projects/{project_id}", json={"status": "archived"})
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/projects/{theirs.id}", json={"title": "Not theirs"})
    ).status_code == 403


async def test_a_signed_in_student_sees_the_project_their_membership_grants(
    client: AsyncClient,
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    # This is the wiring check: the loader registered by projects must reach the session Scope.
    project = await service.create_project(db, prof_scope, title="Joined", stage="implementation")
    await service.create_project(db, prof_scope, title="Not joined", stage="theory")
    await service.add_member(db, prof_scope, project.id, student_id=student_a.id)

    await _sign_in(client, student_a)
    response = await client.get("/api/v1/projects")

    assert [item["title"] for item in response.json()["items"]] == ["Joined"]


async def test_a_non_member_gets_404_for_the_project(
    client: AsyncClient, db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await service.create_project(db, prof_scope, title="Closed", stage="theory")
    await _sign_in(client, student_a)

    response = await client.get(f"/api/v1/projects/{project.id}")

    assert response.status_code == 404


async def test_the_professor_manages_membership(
    client: AsyncClient,
    db: AsyncSession,
    prof: identity_models.User,
    prof_scope: Scope,
    student_a: identity_models.User,
) -> None:
    project = await service.create_project(db, prof_scope, title="Baseline", stage="analysis")
    await _sign_in(client, prof)

    added = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"student_id": str(student_a.id), "responsibility": "Evaluation harness"},
    )
    assert added.status_code == 201

    listed = await client.get(f"/api/v1/projects/{project.id}/members")
    assert [m["student_id"] for m in listed.json()] == [str(student_a.id)]

    ended = await client.post(
        f"/api/v1/projects/{project.id}/members/{added.json()['id']}/end", json={}
    )
    assert ended.status_code == 200
    assert ended.json()["left_on"] is not None


async def test_milestones_tasks_and_progress_are_reachable(
    client: AsyncClient, db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    project = await service.create_project(db, prof_scope, title="Baseline", stage="implementation")
    await _sign_in(client, prof)

    milestone = await client.post(
        f"/api/v1/projects/{project.id}/milestones",
        json={"title": "Reproduce the baseline", "weight": "3", "success_criteria": "Within 1pt"},
    )
    assert milestone.status_code == 201

    task = await client.post(
        f"/api/v1/projects/{project.id}/tasks",
        json={"title": "Run the sweep", "milestone_id": milestone.json()["id"]},
    )
    assert task.status_code == 201

    progress = await client.get(f"/api/v1/projects/{project.id}/progress")
    assert progress.json()["milestone_count"] == 1


async def test_a_milestone_baseline_change_needs_a_reason_over_http(
    client: AsyncClient, db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    project = await service.create_project(db, prof_scope, title="Baseline", stage="implementation")
    milestone = await service.create_milestone(db, prof_scope, project.id, title="Reproduce")
    await _sign_in(client, prof)

    refused = await client.patch(f"/api/v1/milestones/{milestone.id}", json={"weight": "5"})
    assert refused.status_code == 422

    accepted = await client.patch(
        f"/api/v1/milestones/{milestone.id}",
        json={"weight": "5", "change_reason": "Scope grew to cover the ablation"},
    )
    assert accepted.status_code == 200

    revisions = await client.get(f"/api/v1/milestones/{milestone.id}/revisions")
    assert [r["revision_no"] for r in revisions.json()] == [1, 2]


async def test_the_project_workspace_lists_decisions(
    client: AsyncClient, db: AsyncSession, prof: identity_models.User, prof_scope: Scope
) -> None:
    project = await service.create_project(db, prof_scope, title="Baseline", stage="analysis")
    await _sign_in(client, prof)

    created = await client.post(
        f"/api/v1/projects/{project.id}/decisions",
        json={"decision": "Drop the transformer baseline", "rationale": "Three weeks, no gain."},
    )
    assert created.status_code == 201

    listed = await client.get(f"/api/v1/projects/{project.id}/decisions")
    assert [d["decision"] for d in listed.json()] == ["Drop the transformer baseline"]


async def test_the_project_endpoints_require_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/projects")).status_code == 401


async def test_a_repository_link_must_be_one_a_browser_could_follow(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    # The only thing this field does is get clicked, so a bare host is refused at the edge rather
    # than stored and found broken later.
    await _sign_in(client, student_a)

    refused = await client.post(
        "/api/v1/projects",
        json={"title": "Mine", "stage": "theory", "repo_url": "github.com/lab/mine"},
    )
    assert refused.status_code == 422

    accepted = await client.post(
        "/api/v1/projects",
        json={"title": "Mine", "stage": "theory", "repo_url": "https://github.com/lab/mine"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["repo_url"] == "https://github.com/lab/mine"


async def test_the_optional_repository_field_may_be_left_empty(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    """The field is labelled optional on the form, and leaving it blank used to return a 500.

    `max_length` was constrained on `str | None` rather than on the `str` in it, so it was applied
    to the None that `normalize_repo_url` folds blank and absent into, and pydantic raised
    TypeError inside request validation. A student starting a project before there is a repository
    — the ordinary case — could not create one at all from their own screen.
    """
    await _sign_in(client, student_a)

    for sent in ({}, {"repo_url": None}, {"repo_url": ""}, {"repo_url": "   "}):
        created = await client.post(
            "/api/v1/projects", json={"title": "No repo yet", "stage": "theory", **sent}
        )

        assert created.status_code == 201, created.text
        assert created.json()["repo_url"] is None


async def test_a_repository_link_can_be_taken_off_a_project(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _sign_in(client, student_a)
    created = await client.post(
        "/api/v1/projects",
        json={"title": "Mine", "stage": "theory", "repo_url": "https://github.com/lab/mine"},
    )
    assert created.status_code == 201

    cleared = await client.patch(f"/api/v1/projects/{created.json()['id']}", json={"repo_url": ""})

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["repo_url"] is None


async def test_a_repository_link_longer_than_the_column_is_refused(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    # Still refused, and as a validation failure rather than as a crash: the length constraint
    # moved, it did not go away.
    await _sign_in(client, student_a)

    response = await client.post(
        "/api/v1/projects",
        json={"title": "Mine", "stage": "theory", "repo_url": "https://x.dev/" + "y" * 600},
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("repo_url:")
