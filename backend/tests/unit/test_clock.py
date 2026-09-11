"""REP-01 / REP-08 calendar arithmetic."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.clock import deadline_for_meeting, next_weekday_on_or_after, reminder_due

TZ = "Asia/Ho_Chi_Minh"  # UTC+7, no daylight saving


@pytest.mark.unit
def test_deadline_is_2359_local_on_day_before_meeting() -> None:
    # Meeting Monday 2026-09-14 -> deadline Sunday 2026-09-13 23:59 local = 16:59 UTC
    assert deadline_for_meeting(date(2026, 9, 14), TZ) == datetime(2026, 9, 13, 16, 59, tzinfo=UTC)


@pytest.mark.unit
def test_reminder_fires_at_local_midnight_on_meeting_day() -> None:
    deadline = deadline_for_meeting(date(2026, 9, 14), TZ)
    due = reminder_due(deadline)
    assert due == datetime(2026, 9, 13, 17, 0, tzinfo=UTC)  # 00:00 local on 2026-09-14


@pytest.mark.unit
@pytest.mark.parametrize(
    ("day", "weekday", "expected"),
    [
        (date(2026, 9, 9), 0, date(2026, 9, 14)),  # Wednesday -> next Monday
        (date(2026, 9, 14), 0, date(2026, 9, 14)),  # Monday -> same day
        (date(2026, 9, 14), 6, date(2026, 9, 20)),  # Monday -> Sunday
    ],
)
def test_next_weekday_on_or_after(day: date, weekday: int, expected: date) -> None:
    assert next_weekday_on_or_after(day, weekday) == expected
