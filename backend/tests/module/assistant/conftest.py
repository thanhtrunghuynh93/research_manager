"""A small workspace with a submitted week, shared by the assistant's service tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity import models as identity_models
from tests.factories import Week, make_entry, make_week, submit

AFTER_THE_WEEK = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)


@pytest.fixture
def one_week_open(monkeypatch: pytest.MonkeyPatch, frozen_now: Callable[[datetime], None]) -> None:
    # Saving a calendar opens the weeks ahead of the reporting clock. Pinned inside the week of
    # 14 September with no horizon, that week is the only one open — the world these helpers
    # describe. Left to the wall clock, the week of the 21st opened too and became "this week".
    frozen_now(datetime(2026, 9, 15, 3, 0, tzinfo=UTC))
    monkeypatch.setattr("app.reporting.service.DEFAULT_HORIZON", timedelta(0), raising=True)


@pytest.fixture
def build_week(one_week_open: None) -> Callable[..., Any]:
    """`make_week`, in a world where the week of 14 September is the only one open."""
    return make_week


async def submit_entry(
    db: AsyncSession, student: identity_models.User, week: Week, **fields: str
) -> Any:
    """Submit one entry, with no plan, on the week's project; override any field by keyword."""
    entry = make_entry(
        week.project.id,
        work="Implemented the loader and ran the BM25 baseline.",
        results="nDCG@10 reached 0.412 on the internal split.",
        next_plan={},
    )
    return await submit(db, student, week, {**entry, **fields})
