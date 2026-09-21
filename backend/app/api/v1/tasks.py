"""Weekly tasks (PROJ-03).

Split out of the old `milestones.py` when milestones were removed: the tasks outlived them,
because a task is what a plan baseline freezes (PROJ-04) and milestones were only ever something
a task could optionally point at.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.projects import service
from app.projects.schemas import TaskIn, TaskOut, TaskPatch

router = APIRouter(tags=["tasks"])


@router.get("/projects/{project_id}/tasks", summary="List tasks")
async def list_tasks(project_id: UUID, scope: ScopeDep, session: SessionDep) -> list[TaskOut]:
    return await service.list_tasks(session, scope, project_id)


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
