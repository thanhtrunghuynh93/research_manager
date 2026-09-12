"""What a spent budget does to an assessment run (requirements §11, architecture §10).

The requirement is precise about this: a budget that runs out must produce "clear delayed-analysis
states", not a failure and not a silently missing assessment. The professor has to be able to see
that the week was not assessed *because the money ran out*, which is a different problem from a
model that failed and a different problem again from a student who submitted nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import cost
from app.ai.gateway import Budget, CallContext, Result, Schema
from app.assessment import models, service
from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.module


class _DelayedGateway:
    """A gateway whose budget check has already failed, which is what the real one returns."""

    model = "gpt-4.1"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured(
        self,
        *,
        prompt_id: str,
        inputs: dict[str, Any],
        schema: type[Schema],
        budget: Budget,
        context: CallContext,
    ) -> Result[Schema]:
        self.calls += 1
        return Result(
            value=None,
            model=self.model,
            prompt_version=context.prompt_version,
            error="delayed_budget",
            notes=["the workspace AI budget for this month is spent"],
        )

    async def embed(self, texts: list[str], **billing: Any) -> list[list[float]]:
        from app.evidence.index.embeddings import DeterministicEmbedder

        return await DeterministicEmbedder().embed(texts)


async def _submitted_week(
    db: AsyncSession, prof_scope: Scope, student: identity_models.User
) -> tuple[Any, Any]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    scope = await identity_service.scope_for(db, student)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": "Implemented the loader and ran the baseline.",
                "results": "The baseline reproduces the published score.",
            }
        ],
    )
    return period, project


async def test_a_spent_budget_leaves_the_run_delayed_rather_than_failed(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    period, project = await _submitted_week(db, prof_scope, student_a)

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=_DelayedGateway(),
    )

    assert assessment is None, "no draft is invented from a call that never happened"
    run = await service.latest_run(
        db, student_id=student_a.id, project_id=project.id, period_id=period.id
    )
    assert run is not None
    assert run.state is models.RunState.DELAYED_BUDGET
    assert "budget" in (run.error_summary or "")


async def test_the_run_stays_retryable_so_raising_the_budget_is_enough(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """AC-13: a job that could not run must be able to run later without duplicating anything."""
    from app.ai.fake import FakeGateway

    period, project = await _submitted_week(db, prof_scope, student_a)
    await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=_DelayedGateway(),
    )

    assessment = await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=FakeGateway(),
    )

    assert assessment is not None
    assert assessment.version_no == 1, "the delayed attempt did not consume a version number"


async def test_the_pipeline_tells_the_gateway_which_workspace_is_paying(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """Without this the ledger cannot attribute a call, and a budget cannot be enforced."""
    seen: list[CallContext] = []

    class _Watching(_DelayedGateway):
        async def complete_structured(self, **kwargs: Any) -> Result[Any]:
            seen.append(kwargs["context"])
            return await super().complete_structured(**kwargs)

    period, project = await _submitted_week(db, prof_scope, student_a)
    await service.run_pipeline(
        db,
        student_id=student_a.id,
        project_id=project.id,
        period_id=period.id,
        gateway=_Watching(),
    )

    assert seen
    assert seen[0].workspace_id == prof_scope.workspace_id
    assert seen[0].project_id == project.id
    assert seen[0].session is db
    assert seen[0].subject_email == student_a.email


async def test_the_budget_state_is_readable_for_the_review_queue(
    db: AsyncSession, prof_scope: Scope, workspace: identity_models.Workspace
) -> None:
    await identity_service.set_ai_budgets(db, prof_scope, {"monthly_usd": "0.50"})
    await cost.record_call(
        db,
        workspace_id=workspace.id,
        prompt_id="rate_rubric",
        prompt_version="v1",
        model="gpt-4.1",
        tokens_in=1_000_000,
        tokens_out=0,
    )

    state = await cost.check_budget(db, workspace_id=workspace.id, project_id=None)

    assert state.allowed is False
    assert "budget" in state.reason
