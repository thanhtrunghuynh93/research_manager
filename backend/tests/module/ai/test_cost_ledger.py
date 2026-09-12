"""The cost ledger and budgets (requirements §11 "Cost control", architecture §10).

Two things must be true for the professor to trust this system with a paid API: every call is on
the record with what it cost, and going over a budget delays the analysis visibly instead of
failing somewhere quiet.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import cost
from app.core.authz import Scope
from app.core.ids import uuid7
from app.identity import models as identity_models
from app.identity import service as identity_service

pytestmark = pytest.mark.module


@pytest.fixture
def project_ids() -> tuple[object, object]:
    """The ledger records a project id without owning the project: no cross-module foreign key."""
    return uuid7(), uuid7()


async def _call(
    db: AsyncSession,
    workspace: identity_models.Workspace,
    *,
    tokens_in: int = 1000,
    tokens_out: int = 500,
    model: str = "gpt-4.1",
    status: str = "completed",
    project_id: object = None,
    at: datetime | None = None,
) -> cost.LedgerEntry:
    entry = await cost.record_call(
        db,
        workspace_id=workspace.id,
        project_id=project_id,
        prompt_id="rate_rubric",
        prompt_version="v1",
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=1200,
        status=status,
        at=at,
    )
    await db.flush()
    return entry


async def test_every_call_is_recorded_with_the_prompt_and_model_that_made_it(
    db: AsyncSession, workspace: identity_models.Workspace
) -> None:
    entry = await _call(db, workspace)

    assert entry.prompt_id == "rate_rubric"
    assert entry.prompt_version == "v1"
    assert entry.model == "gpt-4.1"
    assert entry.tokens_in == 1000
    assert entry.tokens_out == 500


async def test_the_cost_of_a_priced_model_is_computed_from_its_published_rate(
    db: AsyncSession, workspace: identity_models.Workspace
) -> None:
    entry = await _call(db, workspace, tokens_in=1_000_000, tokens_out=1_000_000)

    rate = cost.PRICES["gpt-4.1"]
    assert entry.cost_usd == (rate.input_per_mtok + rate.output_per_mtok).quantize(
        Decimal("0.000001")
    )


async def test_an_unpriced_model_records_tokens_and_leaves_the_cost_unknown(
    db: AsyncSession, workspace: identity_models.Workspace
) -> None:
    """A guessed price is worse than no price: the tokens are the fact, the money is an estimate."""
    entry = await _call(db, workspace, model="some-new-model")

    assert entry.cost_usd is None
    assert entry.tokens_in == 1000


async def test_a_failed_call_is_still_on_the_record(
    db: AsyncSession, workspace: identity_models.Workspace
) -> None:
    """A provider error costs time and sometimes tokens; hiding it hides the reason for a retry."""
    entry = await _call(db, workspace, status="failed", tokens_out=0)

    assert entry.status == "failed"

    usage = await cost.usage(db, workspace_id=workspace.id)
    assert usage.calls == 1
    assert usage.failed == 1


async def test_usage_is_reported_per_project_and_per_month(
    db: AsyncSession, workspace: identity_models.Workspace, project_ids: tuple[object, object]
) -> None:
    first, second = project_ids
    now = datetime.now(UTC)
    await _call(db, workspace, project_id=first, tokens_in=1_000_000, tokens_out=0, at=now)
    await _call(db, workspace, project_id=second, tokens_in=2_000_000, tokens_out=0, at=now)
    await _call(
        db,
        workspace,
        project_id=first,
        tokens_in=4_000_000,
        tokens_out=0,
        at=now - timedelta(days=60),
    )

    this_month = await cost.usage(db, workspace_id=workspace.id, since=_month_start(now))
    assert this_month.calls == 2
    assert this_month.tokens_in == 3_000_000

    for_first = await cost.usage(
        db, workspace_id=workspace.id, project_id=first, since=_month_start(now)
    )
    assert for_first.calls == 1
    assert for_first.tokens_in == 1_000_000


async def test_without_a_configured_budget_nothing_is_delayed(
    db: AsyncSession, workspace: identity_models.Workspace
) -> None:
    """A budget the professor has not set is not a budget of zero."""
    state = await cost.check_budget(db, workspace_id=workspace.id, project_id=None)

    assert state.allowed is True
    assert state.limit_usd is None


async def test_a_workspace_budget_that_is_spent_delays_the_next_call(
    db: AsyncSession,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
) -> None:
    await identity_service.set_ai_budgets(db, prof_scope, {"monthly_usd": "1.00"})
    await _call(db, workspace, tokens_in=2_000_000, tokens_out=2_000_000)

    state = await cost.check_budget(db, workspace_id=workspace.id, project_id=None)

    assert state.allowed is False
    assert state.reason
    assert state.limit_usd == Decimal("1.00")


async def test_a_project_budget_binds_only_that_project(
    db: AsyncSession,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
    project_ids: tuple[object, object],
) -> None:
    first, second = project_ids
    await identity_service.set_ai_budgets(
        db, prof_scope, {"project_monthly_usd": {str(first): "0.01"}}
    )
    await _call(db, workspace, project_id=first, tokens_in=2_000_000, tokens_out=2_000_000)

    blocked = await cost.check_budget(db, workspace_id=workspace.id, project_id=first)
    open_one = await cost.check_budget(db, workspace_id=workspace.id, project_id=second)

    assert blocked.allowed is False
    assert open_one.allowed is True


async def test_crossing_four_fifths_of_a_budget_raises_a_warning_but_still_allows_the_call(
    db: AsyncSession,
    prof_scope: Scope,
    workspace: identity_models.Workspace,
) -> None:
    """Architecture §15: alert at 80 %. An alert is not a stop."""
    await identity_service.set_ai_budgets(db, prof_scope, {"monthly_usd": "10.00"})
    # gpt-4.1 at 2 USD per Mtok in: 4.5 Mtok in is 9.00 USD, which is 90 % of the budget.
    await _call(db, workspace, tokens_in=4_500_000, tokens_out=0)

    state = await cost.check_budget(db, workspace_id=workspace.id, project_id=None)

    assert state.allowed is True
    assert state.warning is True


async def test_only_the_professor_may_set_a_budget(
    db: AsyncSession, student_a_scope: Scope
) -> None:
    from app.core.errors import ForbiddenError

    with pytest.raises(ForbiddenError):
        await identity_service.set_ai_budgets(db, student_a_scope, {"monthly_usd": "5"})


def _month_start(moment: datetime) -> datetime:
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
