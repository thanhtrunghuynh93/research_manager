"""Pure reporting-calendar arithmetic (REP-01). No database, no clock reads — easy to test.

The deadline is fixed by rule: 23:59 local on the day before the weekly meeting, and the meeting is
the first configured meeting weekday after the period it discusses. With the proposed default —
week Monday to Sunday, meeting Monday — the week of Mon 14 to Sun 20 September is discussed on
Mon 21 and is due Sun 20 at 23:59 local.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.core.clock import (
    DEADLINE_LOCAL_TIME,
    next_weekday_on_or_after,
    reminder_due,
    to_utc,
)

WEEK_LENGTH = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class PeriodDates:
    local_start: date
    local_end: date
    start_utc: datetime
    end_utc: datetime
    meeting_date: date
    deadline_utc: datetime
    reminder_due_utc: datetime


def first_period_start(effective_from: date, week_start_weekday: int) -> date:
    return next_weekday_on_or_after(effective_from, week_start_weekday)


def next_period_start(previous_local_end: date, week_start_weekday: int) -> date:
    return next_weekday_on_or_after(previous_local_end + timedelta(days=1), week_start_weekday)


def period_dates(
    local_start: date, *, meeting_weekday: int, timezone: str, grace_minutes: int = 0
) -> PeriodDates:
    local_end = local_start + timedelta(days=6)
    # The meeting follows the week it discusses, so the deadline lands inside the period.
    meeting_date = next_weekday_on_or_after(local_end + timedelta(days=1), meeting_weekday)
    deadline_utc = to_utc(meeting_date - timedelta(days=1), DEADLINE_LOCAL_TIME, timezone)
    return PeriodDates(
        local_start=local_start,
        local_end=local_end,
        start_utc=to_utc(local_start, time(0, 0), timezone),
        end_utc=to_utc(local_end + timedelta(days=1), time(0, 0), timezone),
        meeting_date=meeting_date,
        deadline_utc=deadline_utc,
        # After the grace closes, not after the deadline: telling a student they missed a deadline
        # they are still inside is worse than telling them a minute later (REP-08).
        reminder_due_utc=reminder_due(deadline_utc + timedelta(minutes=grace_minutes)),
    )


def effective_deadline(
    deadline_utc: datetime, *, grace_minutes: int, extension_until_utc: datetime | None
) -> datetime:
    """The instant after which a submission counts as late, for one obligation.

    The grace period softens the clock for everyone; an extension applies to one obligation only
    (REP-01, REP-06). The report's own timestamp is stored unchanged either way.
    """
    with_grace = deadline_utc + timedelta(minutes=grace_minutes)
    if extension_until_utc is not None and extension_until_utc > with_grace:
        return extension_until_utc
    return with_grace
