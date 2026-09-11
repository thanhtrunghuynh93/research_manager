"""Milestones, their retained baselines, and weekly tasks (PROJ-03, PROJ-06)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.projects import service
from app.projects.schemas import (
    MilestoneIn,
    MilestoneOut,
    MilestonePatch,
    MilestoneRevisionOut,
    TaskIn,
    TaskOut,
    TaskPatch,
)

router = APIRouter(tags=["milestones"])


@router.get("/projects/{project_id}/milestones", summary="List milestones")
async def list_milestones(
    project_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[MilestoneOut]:
    return await service.list_milestones(session, scope, project_id)


@router.post(
    "/projects/{project_id}/milestones",
    status_code=status.HTTP_201_CREATED,
    summary="Create a milestone",
)
async def create_milestone(
    project_id: UUID, payload: MilestoneIn, scope: ProfScopeDep, session: SessionDep
) -> MilestoneOut:
    return await service.create_milestone(
        session, scope, project_id, **payload.model_dump(exclude_unset=True)
    )


@router.patch("/milestones/{milestone_id}", summary="Update a milestone")
async def update_milestone(
    milestone_id: UUID, payload: MilestonePatch, scope: ProfScopeDep, session: SessionDep
) -> MilestoneOut:
    changes = payload.model_dump(exclude_unset=True)
    return await service.update_milestone(
        session, scope, milestone_id, change_reason=changes.pop("change_reason", None), **changes
    )


@router.get(
    "/milestones/{milestone_id}/revisions",
    summary="The retained baselines of a milestone",
)
async def list_milestone_revisions(
    milestone_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[MilestoneRevisionOut]:
    return await service.list_milestone_revisions(session, scope, milestone_id)


@router.get("/projects/{project_id}/tasks", summary="List tasks")
async def list_tasks(
    project_id: UUID,
    scope: ScopeDep,
    session: SessionDep,
    milestone_id: UUID | None = None,
) -> list[TaskOut]:
    return await service.list_tasks(session, scope, project_id, milestone_id=milestone_id)


@router.post(
    "/projects/{project_id}/tasks",
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
async def create_task(
    project_id: UUID, payload: TaskIn, scope: ProfScopeDep, session: SessionDep
) -> TaskOut:
    return await service.create_task(
        session, scope, project_id, **payload.model_dump(exclude_unset=True)
    )


@router.patch("/tasks/{task_id}", summary="Update a task or report progress on it")
async def update_task(
    task_id: UUID, payload: TaskPatch, scope: ScopeDep, session: SessionDep
) -> TaskOut:
    return await service.update_task(
        session, scope, task_id, **payload.model_dump(exclude_unset=True)
    )
