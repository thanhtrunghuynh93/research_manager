"""Operations, professor only (architecture §12, docs/repo_layout.md §3.1).

What a stalled worker, a revoked GitHub credential, or a spent budget have in common is that the
student-facing symptom is the same: an assessment that never appeared. These routes exist so the
cause is visible in the product rather than in a log on the host.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import ProfScopeDep, SessionDep
from app.assessment import ops
from app.assessment import service as assessment_service
from app.assessment.schemas import AssessmentOut
from app.evidence import service as evidence_service
from app.evidence.schemas import SyncRunOut

router = APIRouter(prefix="/admin", tags=["admin"])


class AiUsageOut(BaseModel):
    calls: int
    failed: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    # True when a model in this window has no published rate here, so the total is a floor.
    cost_incomplete: bool
    since: datetime


class AiBudgetsOut(BaseModel):
    monthly_usd: str | None = None
    project_monthly_usd: dict[str, str] = Field(default_factory=dict)
    spent_usd: Decimal
    analysis_delayed: bool
    warning: bool
    reason: str


class AiBudgetsIn(BaseModel):
    monthly_usd: str | None = None
    project_monthly_usd: dict[str, str] = Field(default_factory=dict)


class RepositoryHealth(BaseModel):
    """One repository's sync state, so a stale source is named rather than read as no work."""

    repository_id: UUID
    full_name: str
    last_run: SyncRunOut | None = None


@router.get("/ai/usage", summary="Model spend this month")
async def ai_usage(
    scope: ProfScopeDep,
    session: SessionDep,
    project_id: UUID | None = None,
) -> AiUsageOut:
    usage = await ops.ai_usage(session, scope, project_id=project_id)
    return AiUsageOut(**asdict(usage))


@router.get("/ai/budgets", summary="Configured budgets and whether they are delaying analysis")
async def ai_budgets(scope: ProfScopeDep, session: SessionDep) -> AiBudgetsOut:
    return AiBudgetsOut(**asdict(await ops.ai_budgets(session, scope)))


@router.put("/ai/budgets", summary="Set the monthly budgets")
async def set_ai_budgets(
    payload: AiBudgetsIn, scope: ProfScopeDep, session: SessionDep
) -> AiBudgetsOut:
    budgets = await ops.set_ai_budgets(
        session,
        scope,
        monthly_usd=payload.monthly_usd,
        project_monthly_usd=payload.project_monthly_usd,
    )
    return AiBudgetsOut(**asdict(budgets))


@router.get("/sync", summary="Repository sync health")
async def sync_health(scope: ProfScopeDep, session: SessionDep) -> list[RepositoryHealth]:
    """UI-01: last successful sync, covered range, and authorization errors (REPO-05)."""
    repositories = await evidence_service.list_repositories(session, scope)
    return [
        RepositoryHealth(
            repository_id=repository.id,
            full_name=repository.full_name,
            last_run=await evidence_service.sync_status(session, scope, repository.id),
        )
        for repository in repositories
    ]


@router.post("/assessments/retry", summary="Re-run one assessment pipeline")
async def retry_assessment(
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
    scope: ProfScopeDep,
    session: SessionDep,
) -> AssessmentOut | None:
    """Every step is idempotent on its key, so a retry produces no duplicate (architecture §12)."""
    return await assessment_service.run_pipeline(
        session, student_id=student_id, project_id=project_id, period_id=period_id
    )
