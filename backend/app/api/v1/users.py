"""User directory and account administration (AUTH-01, AUTH-02).

Reads are filtered by the caller's Scope, so a record the caller may not see is reported as absent
rather than forbidden: a 403 would itself disclose that the record exists (AC-02).

There is no route to change a role. A role is fixed at acceptance and moves afterwards only
through the break-glass procedure, so with two roles the endpoint had no valid transition left
(ADR 0011).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.core.pagination import Page
from app.identity import service
from app.identity.schemas import (
    InvitationIn,
    InvitationOut,
    MoveStudentIn,
    ProfilePatch,
    UserOut,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", summary="List the users the caller may see")
async def list_users(
    scope: ScopeDep,
    session: SessionDep,
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = None,
) -> Page[UserOut]:
    """Every account in every workspace the caller belongs to; each row carries its own
    `workspace_id` (ADR 0016). For a student, who belongs to one, that is themselves."""
    return await service.list_users(session, scope, limit=limit, cursor=cursor)


@router.patch("/me", summary="Update the caller's own profile")
async def update_own_profile(
    payload: ProfilePatch, scope: ScopeDep, session: SessionDep
) -> UserOut:
    return await service.update_profile(session, scope, display_name=payload.display_name)


@router.post(
    "/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a student, or a colleague as a professor",
)
async def invite_user(
    payload: InvitationIn, scope: ProfScopeDep, session: SessionDep
) -> InvitationOut:
    invited = await service.invite_user(
        session,
        scope,
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
        workspace_id=payload.workspace_id,
    )
    return invited.invitation


@router.get("/{user_id}", summary="Read one user")
async def get_user(user_id: UUID, scope: ScopeDep, session: SessionDep) -> UserOut:
    return await service.get_user(session, scope, user_id)


@router.post("/{user_id}/remove", summary="Remove a student from the workspace")
async def remove_student(user_id: UUID, scope: ProfScopeDep, session: SessionDep) -> UserOut:
    """Ends every project membership, then closes the account. Not reversible: a student who
    returns is invited again (ADR 0011). A professor account is refused — that is break-glass."""
    return await service.remove_student(session, scope, user_id)


@router.post("/{user_id}/workspace", summary="Move a student to another workspace")
async def move_student(
    user_id: UUID, payload: MoveStudentIn, scope: ProfScopeDep, session: SessionDep
) -> UserOut:
    """Only a student who has not started work: their history is pinned to the workspace it was
    written in, and the database refuses the move rather than dragging it along (ADR 0014)."""
    return await service.move_student(session, scope, user_id, workspace_id=payload.workspace_id)


@router.post("/{user_id}/deactivate", summary="Suspend an account's access")
async def deactivate_user(user_id: UUID, scope: ProfScopeDep, session: SessionDep) -> UserOut:
    return await service.deactivate_user(session, scope, user_id)


@router.post("/{user_id}/reactivate", summary="Reactivate an account")
async def reactivate_user(user_id: UUID, scope: ProfScopeDep, session: SessionDep) -> UserOut:
    return await service.reactivate_user(session, scope, user_id)
