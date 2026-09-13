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


async def test_a_student_cannot_create_a_project(
    client: AsyncClient, student_a: identity_models.User
) -> None:
    await _sign_in(client, student_a)

    response = await client.post("/api/v1/projects", json={"title": "Mine", "stage": "theory"})

    assert response.status_code == 403


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
