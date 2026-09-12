"""The professor overview (UI-01).

One request behind one screen, assembled from the same fact functions the assistant uses. That is
deliberate: the number on the dashboard and the number in the answer are computed by the same
code, so they cannot disagree and then have to be reconciled by whoever is reading them.

Every section is always present, even when empty. A missing section reads as a broken screen; an
empty one reads as nothing to do.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ProfScopeDep, SessionDep
from app.assessment import ops
from app.assistant import facts
from app.core.clock import now

router = APIRouter(tags=["overview"])


class CurrentPeriod(BaseModel):
    period_id: str
    local_start: str
    local_end: str
    meeting_date: str
    deadline_utc: str
    timezone: str


class Outstanding(BaseModel):
    """REP-08: who still owes a report, after exemptions and extensions, at a stated instant."""

    count: int
    as_of: datetime
    entries: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""


class BudgetState(BaseModel):
    analysis_delayed: bool
    warning: bool
    reason: str
    spent_usd: str
    monthly_usd: str | None = None


class OverviewOut(BaseModel):
    as_of: datetime
    current_period: CurrentPeriod | None = None
    outstanding: Outstanding
    review_queue: list[dict[str, Any]] = Field(default_factory=list)
    # AC-04: named as stale evidence, never rendered as an absence of work.
    sync_issues: list[dict[str, Any]] = Field(default_factory=list)
    # AC-13: runs that stopped short, with the reason, so a retry is an informed decision.
    stalled_analyses: list[dict[str, Any]] = Field(default_factory=list)
    ai_budget: BudgetState


@router.get("/overview", summary="The professor's current week at a glance")
async def overview(scope: ProfScopeDep, session: SessionDep) -> OverviewOut:
    as_of = now()
    query = facts.FactQuery(scope=scope, as_of=as_of)

    deadline = await facts.run(session, "next_deadline", query)
    outstanding = await facts.run(session, "missing_reports", query)
    queue = await facts.run(session, "review_queue", query)
    stale = await facts.run(session, "stale_repositories", query)
    stalled = await facts.run(session, "stalled_analyses", query)
    budgets = await ops.ai_budgets(session, scope)

    return OverviewOut(
        as_of=as_of,
        current_period=(
            CurrentPeriod(
                period_id=deadline.rows[0]["period_id"],
                local_start=deadline.rows[0]["local_start"],
                local_end=deadline.rows[0]["local_end"],
                meeting_date=deadline.rows[0]["meeting_date"],
                deadline_utc=deadline.rows[0]["deadline_utc"],
                timezone=deadline.rows[0]["timezone"],
            )
            if deadline is not None and deadline.rows
            else None
        ),
        outstanding=Outstanding(
            count=int(outstanding.value) if outstanding is not None else 0,
            as_of=as_of,
            entries=outstanding.rows if outstanding is not None else [],
            note=outstanding.note if outstanding is not None else "",
        ),
        review_queue=queue.rows if queue is not None else [],
        sync_issues=stale.rows if stale is not None else [],
        stalled_analyses=stalled.rows if stalled is not None else [],
        ai_budget=BudgetState(
            analysis_delayed=budgets.analysis_delayed,
            warning=budgets.warning,
            reason=budgets.reason,
            spent_usd=str(budgets.spent_usd),
            monthly_usd=budgets.monthly_usd,
        ),
    )
