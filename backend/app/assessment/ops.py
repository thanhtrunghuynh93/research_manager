"""What operations needs to see, assembled where the AI gateway may be reached.

`app.api` may not import `app.ai` (docs/repo_layout.md §3.3), and that contract is worth keeping
exactly as it is: the point of it is that no other module can send content to a provider. Reading
the cost ledger is not sending anything, but a narrower contract would be a contract nobody could
check at a glance. So the assessment module — which is allowed the gateway, and which is the module
that spends the money — exposes the spend alongside the runs it paid for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import cost
from app.core.authz import Scope


@dataclass(frozen=True, slots=True)
class AiUsage:
    """Spend in a window. `cost_incomplete` says the total is a floor, not the whole bill."""

    calls: int
    failed: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    cost_incomplete: bool
    since: datetime


@dataclass(frozen=True, slots=True)
class AiBudgets:
    """The configured limits and whether they are currently stopping anything."""

    monthly_usd: str | None
    project_monthly_usd: dict[str, str]
    spent_usd: Decimal
    analysis_delayed: bool
    warning: bool
    reason: str


async def ai_usage(
    session: AsyncSession,
    scope: Scope,
    *,
    project_id: UUID | None = None,
    since: datetime | None = None,
) -> AiUsage:
    scope.require_prof()
    start = since or cost.month_start()
    usage = await cost.usage(
        session, workspace_id=scope.workspace_id, project_id=project_id, since=start
    )
    return AiUsage(
        calls=usage.calls,
        failed=usage.failed,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        cost_usd=usage.cost_usd,
        cost_incomplete=usage.cost_incomplete,
        since=start,
    )


async def ai_budgets(session: AsyncSession, scope: Scope) -> AiBudgets:
    from app.identity import service as identity_service

    scope.require_prof()
    budgets = await identity_service.ai_budgets(session, scope.workspace_id)
    state = await cost.check_budget(session, workspace_id=scope.workspace_id, project_id=None)
    return AiBudgets(
        monthly_usd=_as_text(budgets.get("monthly_usd")),
        project_monthly_usd={
            str(key): str(value)
            for key, value in (budgets.get("project_monthly_usd") or {}).items()
        },
        spent_usd=state.spent_usd,
        analysis_delayed=not state.allowed,
        warning=state.warning,
        reason=state.reason,
    )


async def set_ai_budgets(
    session: AsyncSession,
    scope: Scope,
    *,
    monthly_usd: str | None,
    project_monthly_usd: dict[str, str],
) -> AiBudgets:
    from app.identity import service as identity_service

    scope.require_prof()
    await identity_service.set_ai_budgets(
        session,
        scope,
        {"monthly_usd": monthly_usd, "project_monthly_usd": project_monthly_usd},
    )
    return await ai_budgets(session, scope)


def _as_text(value: object) -> str | None:
    return None if value is None else str(value)
