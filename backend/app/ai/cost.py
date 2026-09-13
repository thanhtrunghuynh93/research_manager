"""Cost ledger and budgets (requirements §11 "Cost control", architecture §10).

The professor is paying for these calls out of a research budget, so two things have to hold.
Every call is on the record, including the ones that failed, because a retry loop that costs money
is exactly the thing you want to see. And when a budget is spent the analysis is *delayed*, with
that state visible in the review queue — not dropped, not silently retried, and not carried on
past the limit.

Prices are a published rate applied by arithmetic. A model with no rate in the table records its
tokens and leaves the cost null: an invented price would be worse than an honest gap, because it
would be believed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiCall
from app.ai.models import CallStatus as CallStatus  # re-exported: the gateway records with it
from app.core.clock import now

log = logging.getLogger(__name__)

MICRO = Decimal("0.000001")
WARNING_FRACTION = Decimal("0.8")  # architecture §15: alert at 80 % of a budget


@dataclass(frozen=True, slots=True)
class Price:
    """USD per million tokens, as published by the provider."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal


# Rates as configured for this deployment. They are data, not a claim about current provider
# pricing: when a rate changes, change it here and the ledger's later rows follow.
PRICES: dict[str, Price] = {
    "gpt-4.1": Price(Decimal("2.00"), Decimal("8.00")),
    "gpt-4.1-mini": Price(Decimal("0.40"), Decimal("1.60")),
    "gpt-4o": Price(Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": Price(Decimal("0.15"), Decimal("0.60")),
    "text-embedding-3-small": Price(Decimal("0.02"), Decimal("0")),
    "text-embedding-3-large": Price(Decimal("0.13"), Decimal("0")),
}


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """What was written, returned so a caller can log or surface it without a second read."""

    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    prompt_id: str
    prompt_version: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None
    latency_ms: int
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Usage:
    calls: int = 0
    failed: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    # True when at least one call in the window used a model with no published rate, so the
    # total below is a floor rather than the whole bill.
    cost_incomplete: bool = False


@dataclass(frozen=True, slots=True)
class BudgetState:
    """Whether the next call may go ahead, and the reason if not."""

    allowed: bool
    spent_usd: Decimal = Decimal("0")
    limit_usd: Decimal | None = None
    warning: bool = False
    reason: str = ""
    scope: str = "workspace"
    extra: dict[str, Any] = field(default_factory=dict)


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal | None:
    price = PRICES.get(model)
    if price is None:
        return None
    total = (
        price.input_per_mtok * Decimal(tokens_in) + price.output_per_mtok * Decimal(tokens_out)
    ) / Decimal(1_000_000)
    return total.quantize(MICRO)


async def record_call(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    prompt_id: str,
    prompt_version: str,
    model: str,
    project_id: UUID | None = None,
    job_id: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    status: str = CallStatus.COMPLETED,
    redactions: list[str] | None = None,
    at: datetime | None = None,
) -> LedgerEntry:
    """Write one ledger row. Never raises: accounting must not break the thing it accounts for."""
    row = AiCall(
        workspace_id=workspace_id,
        project_id=project_id,
        job_id=job_id,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=estimate_cost(model, tokens_in, tokens_out),
        latency_ms=latency_ms,
        status=CallStatus(status),
        redactions=redactions or [],
    )
    if at is not None:
        row.created_at = at
    session.add(row)
    await session.flush()
    return _entry(row)


async def usage(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Usage:
    """What has been spent in a window, optionally for one project."""
    filters = [AiCall.workspace_id == workspace_id]
    if project_id is not None:
        filters.append(AiCall.project_id == project_id)
    if since is not None:
        filters.append(AiCall.created_at >= since)
    if until is not None:
        filters.append(AiCall.created_at <= until)

    row = (
        await session.execute(
            select(
                func.count(AiCall.id),
                func.coalesce(func.sum(AiCall.tokens_in), 0),
                func.coalesce(func.sum(AiCall.tokens_out), 0),
                func.coalesce(func.sum(AiCall.cost_usd), 0),
                func.count(AiCall.id).filter(AiCall.status == CallStatus.FAILED),
                func.count(AiCall.id).filter(AiCall.cost_usd.is_(None)),
            ).where(*filters)
        )
    ).one()

    return Usage(
        calls=int(row[0]),
        tokens_in=int(row[1]),
        tokens_out=int(row[2]),
        cost_usd=Decimal(row[3]).quantize(MICRO),
        failed=int(row[4]),
        cost_incomplete=int(row[5]) > 0,
    )


def month_start(moment: datetime | None = None) -> datetime:
    at = moment or now()
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def check_budget(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID | None,
    at: datetime | None = None,
) -> BudgetState:
    """May the next call go ahead this month?

    A budget the professor has not configured is not a budget of zero: without a number there is
    nothing to exceed, and the system must not refuse to work because nobody filled in a form.
    """
    from app.identity import service as identity_service

    budgets = await identity_service.ai_budgets(session, workspace_id)
    start = month_start(at)

    project_state: BudgetState | None = None
    project_limit = _limit(_project_limits(budgets).get(str(project_id)))
    if project_id is not None and project_limit is not None:
        spent = (
            await usage(session, workspace_id=workspace_id, project_id=project_id, since=start)
        ).cost_usd
        state = _decide(spent, project_limit, scope="project")
        if not state.allowed:
            return state
        project_state = state

    workspace_limit = _limit(budgets.get("monthly_usd"))
    if workspace_limit is not None:
        spent = (await usage(session, workspace_id=workspace_id, since=start)).cost_usd
        workspace_state = _decide(spent, workspace_limit, scope="workspace")
        # Both limits apply. Returning early on the project *warning* skipped the workspace check
        # entirely, so every project sitting between 80% and 100% of its own budget spent freely
        # against a workspace budget that was already exhausted.
        if not workspace_state.allowed or project_state is None:
            return workspace_state
        return workspace_state if workspace_state.warning else project_state

    return project_state or BudgetState(allowed=True)


def _decide(spent: Decimal, limit: Decimal, *, scope: str) -> BudgetState:
    if limit <= 0:
        return BudgetState(
            allowed=False,
            spent_usd=spent,
            limit_usd=limit,
            scope=scope,
            reason=f"the {scope} AI budget is set to zero",
        )
    if spent >= limit:
        return BudgetState(
            allowed=False,
            spent_usd=spent,
            limit_usd=limit,
            scope=scope,
            reason=(
                f"the {scope} AI budget for this month is spent "
                f"({spent} of {limit} USD); analysis is delayed until it is raised or the "
                "month rolls over"
            ),
        )
    warning = spent >= limit * WARNING_FRACTION
    return BudgetState(
        allowed=True,
        spent_usd=spent,
        limit_usd=limit,
        scope=scope,
        warning=warning,
        reason=(
            f"{spent} of {limit} USD of the {scope} AI budget is used this month" if warning else ""
        ),
    )


def _project_limits(budgets: dict[str, Any]) -> dict[str, Any]:
    raw = budgets.get("project_monthly_usd")
    return raw if isinstance(raw, dict) else {}


def _limit(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        log.warning("ignoring an unreadable AI budget value")
        return None


def _entry(row: AiCall) -> LedgerEntry:
    return LedgerEntry(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        prompt_id=row.prompt_id,
        prompt_version=row.prompt_version,
        model=row.model,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_usd=None if row.cost_usd is None else Decimal(str(row.cost_usd)),
        latency_ms=row.latency_ms,
        status=str(row.status),
        created_at=row.created_at,
    )
