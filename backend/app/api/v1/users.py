"""User directory and account administration (AUTH-01, AUTH-02).

Reads are filtered by the caller's Scope, so a record the caller may not see is reported as absent
rather than forbidden: a 403 would itself disclose that the record exists (AC-02).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.core.pagination import Page
from app.identity import service
from app.identity.schemas import InvitationIn, InvitationOut, ProfilePatch, RolePatch, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", summary="List the users the caller may see")
async def list_users(
    scope: ScopeDep,
    session: SessionDep,
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = None,
) -> Page[UserOut]:
    return await service.list_users(session, scope, limit=limit, cursor=cursor)


@router.patch("/me", summary="Update the caller's own profile")
async def update_own_profile(
    payload: ProfilePatch, scope: ScopeDep, session: SessionDep
) -> UserOut:
    return await service.update_profile(session, scope, display_name=payload.display_name)


@router.post(
    "/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a student or a colleague",
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
    )
    return invited.invitation


@router.get("/{user_id}", summary="Read one user")
async def get_user(user_id: UUID, scope: ScopeDep, session: SessionDep) -> UserOut:
    return await service.get_user(session, scope, user_id)


@router.patch("/{user_id}/role", summary="Change a user's role")
async def set_role(
    user_id: UUID, payload: RolePatch, scope: ProfScopeDep, session: SessionDep
) -> UserOut:
    return await service.set_role(session, scope, user_id, payload.role)


@router.post("/{user_id}/deactivate", summary="Deactivate an account")
async def deactivate_user(user_id: UUID, scope: ProfScopeDep, session: SessionDep) -> UserOut:
    return await service.deactivate_user(session, scope, user_id)


@router.post("/{user_id}/reactivate", summary="Reactivate an account")
async def reactivate_user(user_id: UUID, scope: ProfScopeDep, session: SessionDep) -> UserOut:
    return await service.reactivate_user(session, scope, user_id)
