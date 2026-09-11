"""In-app notifications and their preferences (UI-07)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.notifications import service
from app.notifications.schemas import (
    MuteIn,
    NotificationOut,
    PreferenceOut,
    ReminderOffsetsIn,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", summary="The caller's notifications")
async def list_notifications(
    scope: ScopeDep, session: SessionDep, unread_only: bool = False
) -> list[NotificationOut]:
    return await service.list_notifications(session, scope, unread_only=unread_only)


@router.get("/unread-count", summary="How many are unread")
async def unread_count(scope: ScopeDep, session: SessionDep) -> dict[str, int]:
    return {"unread": await service.unread_count(session, scope)}


@router.post("/{notification_id}/read", summary="Mark one notification read")
async def mark_read(notification_id: UUID, scope: ScopeDep, session: SessionDep) -> NotificationOut:
    return await service.mark_read(session, scope, notification_id)


@router.post("/read-all", summary="Mark every notification read")
async def mark_all_read(scope: ScopeDep, session: SessionDep) -> dict[str, int]:
    return {"marked": await service.mark_all_read(session, scope)}


@router.get("/preferences", summary="Which categories the caller has muted")
async def list_preferences(scope: ScopeDep, session: SessionDep) -> list[PreferenceOut]:
    return await service.list_preferences(session, scope)


@router.post(
    "/preferences/mute",
    status_code=status.HTTP_201_CREATED,
    summary="Mute a non-critical category",
)
async def mute(payload: MuteIn, scope: ScopeDep, session: SessionDep) -> PreferenceOut:
    return await service.mute(session, scope, kind=payload.kind)


@router.post(
    "/preferences/unmute",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unmute a category",
)
async def unmute(payload: MuteIn, scope: ScopeDep, session: SessionDep) -> None:
    await service.unmute(session, scope, kind=payload.kind)


@router.put("/reminder-offsets", summary="How long before the deadline to remind")
async def set_reminder_offsets(
    payload: ReminderOffsetsIn, scope: ProfScopeDep, session: SessionDep
) -> dict[str, list[int]]:
    return {
        "offsets_hours": await service.set_reminder_offsets(
            session, scope, offsets_hours=payload.offsets_hours
        )
    }
