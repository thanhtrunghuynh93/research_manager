"""Time helpers. Use now() everywhere instead of datetime.now() so tests can freeze time.

Reporting-calendar arithmetic lives here because identity, reporting and notifications all need it
(requirements REP-01, REP-08).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEADLINE_LOCAL_TIME = time(23, 59, 0)
REMINDER_OFFSET = timedelta(seconds=60)


def now() -> datetime:
    return datetime.now(tz=UTC)


def to_utc(local_day: date, local_time: time, timezone: str) -> datetime:
    return datetime.combine(local_day, local_time, tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def local_date(instant: datetime, timezone: str) -> date:
    return instant.astimezone(ZoneInfo(timezone)).date()


def deadline_for_meeting(meeting_date: date, timezone: str) -> datetime:
    """REP-01: submission deadline is 23:59 local time on the day before the weekly meeting."""
    return to_utc(meeting_date - timedelta(days=1), DEADLINE_LOCAL_TIME, timezone)


def reminder_due(deadline_utc: datetime) -> datetime:
    """REP-08: the missed-deadline email fires at 00:00 local on the meeting day."""
    return deadline_utc + REMINDER_OFFSET


def next_weekday_on_or_after(day: date, weekday: int) -> date:
    """weekday follows date.weekday(): Monday = 0 … Sunday = 6."""
    return day + timedelta(days=(weekday - day.weekday()) % 7)
