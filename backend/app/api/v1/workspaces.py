"""Workspace administration (ADR 0012).

Ownership is the administration relation: a professor administers the workspaces they own, and
belongs to exactly one. Every route here is professor-only, and a workspace the caller does not
own is reported as absent rather than forbidden — a 403 would itself disclose that it exists
(AC-02).

Creating and archiving is deliberately not symmetric. A workspace is created empty, because a user
belongs to one workspace and the creator already belongs to theirs; it is archived only once it is
empty again, because every foreign key into a workspace cascades and a delete would take the
history with it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ProfScopeDep, SessionDep
from app.identity import service
from app.identity.schemas import WorkspaceCreateIn, WorkspaceOut, WorkspaceUpdateIn

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", summary="The workspaces this professor administers")
async def list_workspaces(scope: ProfScopeDep, session: SessionDep) -> list[WorkspaceOut]:
    return await service.list_workspaces(session, scope)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a workspace and join it")
async def create_workspace(
    payload: WorkspaceCreateIn, scope: ProfScopeDep, session: SessionDep
) -> WorkspaceOut:
    return await service.create_workspace(
        session, scope, name=payload.name, timezone=payload.timezone
    )


@router.post("/{workspace_id}/join", summary="Move your account into this workspace")
async def join_workspace(
    workspace_id: UUID, scope: ProfScopeDep, session: SessionDep
) -> WorkspaceOut:
    return await service.join_workspace(session, scope, workspace_id)


@router.post("/{workspace_id}/leave", summary="Move your account out of this workspace")
async def leave_workspace(
    workspace_id: UUID, scope: ProfScopeDep, session: SessionDep
) -> WorkspaceOut:
    return await service.leave_workspace(session, scope, workspace_id)


@router.get("/{workspace_id}", summary="Read one workspace")
async def get_workspace(
    workspace_id: UUID, scope: ProfScopeDep, session: SessionDep
) -> WorkspaceOut:
    return await service.get_workspace(session, scope, workspace_id)


@router.patch("/{workspace_id}", summary="Rename a workspace or set its timezone")
async def update_workspace(
    workspace_id: UUID, payload: WorkspaceUpdateIn, scope: ProfScopeDep, session: SessionDep
) -> WorkspaceOut:
    return await service.update_workspace(
        session, scope, workspace_id, name=payload.name, timezone=payload.timezone
    )


@router.post("/{workspace_id}/archive", summary="Close a workspace that nobody is left in")
async def archive_workspace(
    workspace_id: UUID, scope: ProfScopeDep, session: SessionDep
) -> WorkspaceOut:
    return await service.archive_workspace(session, scope, workspace_id)
