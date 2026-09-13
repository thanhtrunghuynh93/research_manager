"""Assessments and the review workspace (ASSESS-02, ASSESS-08, UI-05)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.assessment import service
from app.assessment.schemas import (
    ApproveIn,
    AssessmentOut,
    CorrectionIn,
    FeedbackOut,
    ReviewOut,
    SnapshotItemOut,
    SupervisionNoteIn,
    TrendPoint,
)

router = APIRouter(tags=["assessments"])


@router.get("/assessments", summary="Assessments the caller may see")
async def list_assessments(
    scope: ScopeDep,
    session: SessionDep,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    period_id: UUID | None = None,
) -> list[AssessmentOut]:
    """A student sees only versions a review has approved (ASSESS-08)."""
    return await service.list_assessments(
        session, scope, student_id=student_id, project_id=project_id, period_id=period_id
    )


@router.get("/assessments/{assessment_id}", summary="One assessment")
async def get_assessment(
    assessment_id: UUID, scope: ScopeDep, session: SessionDep
) -> AssessmentOut:
    return await service.get_assessment(session, scope, assessment_id)


@router.get(
    "/assessments/{assessment_id}/evidence",
    summary="The evidence snapshot this assessment was made from",
)
async def assessment_evidence(
    assessment_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[SnapshotItemOut]:
    """UI-05: the claims, the evidence, and the draft are read side by side."""
    assessment = await service.get_assessment(session, scope, assessment_id)
    if assessment.snapshot_id is None:
        return []
    return await service.snapshot_items(session, assessment.snapshot_id)


@router.post("/assessments/{assessment_id}/approve", summary="Publish an assessment")
async def approve(
    assessment_id: UUID, payload: ApproveIn, scope: ProfScopeDep, session: SessionDep
) -> ReviewOut:
    """An override needs a recorded reason; the model's own output is kept beside it."""
    return await service.approve(
        session, scope, assessment_id, override=payload.override, rationale=payload.rationale
    )


@router.post("/assessments/{assessment_id}/withdraw", summary="Withdraw an assessment")
async def withdraw(assessment_id: UUID, scope: ProfScopeDep, session: SessionDep) -> ReviewOut:
    return await service.withdraw(session, scope, assessment_id)


@router.post(
    "/assessments/{assessment_id}/corrections",
    status_code=status.HTTP_201_CREATED,
    summary="Request a correction, with evidence",
)
async def request_correction(
    assessment_id: UUID, payload: CorrectionIn, scope: ScopeDep, session: SessionDep
) -> FeedbackOut:
    return await service.request_correction(
        session, scope, assessment_id, body=payload.body, evidence=payload.evidence
    )


@router.get("/assessments/{assessment_id}/feedback", summary="Feedback on an assessment")
async def list_feedback(
    assessment_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[FeedbackOut]:
    return await service.list_feedback(session, scope, assessment_id)


@router.get("/trends", summary="A student's trajectory on one project")
async def progress_series(
    student_id: UUID, project_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[TrendPoint]:
    """Each point carries the rubric that produced it, so a change reads as a break (AC-10)."""
    return await service.progress_series(
        session, scope, student_id=student_id, project_id=project_id
    )


@router.post(
    "/supervision-notes",
    status_code=status.HTTP_201_CREATED,
    summary="Record a private supervision note",
)
async def add_supervision_note(
    payload: SupervisionNoteIn, scope: ProfScopeDep, session: SessionDep
) -> dict[str, str]:
    """QA-06: private to the professor. Never indexed, never in a snapshot, never in an answer."""
    note_id = await service.add_supervision_note(
        session,
        scope,
        body=payload.body,
        student_id=payload.student_id,
        project_id=payload.project_id,
        period_id=payload.period_id,
    )
    return {"id": str(note_id)}
