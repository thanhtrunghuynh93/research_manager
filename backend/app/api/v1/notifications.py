"""Reminder scheduling (UI-07).

The in-app notification surface — reading, marking read, and muting categories — was retired in
use cases v0.3. Notification rows are still written and the missed-deadline mail still goes out;
what is gone is any route that reads them back. This module is what remains: the professor's
control over how long before a deadline a reminder is sent.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ProfScopeDep, SessionDep
from app.notifications import service
from app.notifications.schemas import ReminderOffsetsIn

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.put("/reminder-offsets", summary="How long before the deadline to remind")
async def set_reminder_offsets(
    payload: ReminderOffsetsIn, scope: ProfScopeDep, session: SessionDep
) -> dict[str, list[int]]:
    return {
        "offsets_hours": await service.set_reminder_offsets(
            session, scope, offsets_hours=payload.offsets_hours
        )
    }
