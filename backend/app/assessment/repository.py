"""Queries over the assessment tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment.models import (
    AnalysisRun,
    AssessmentReview,
    AssessmentVersion,
    EvidenceSnapshotItem,
    Feedback,
    ReviewState,
    RubricVersion,
    RunState,
)
from app.core.authz import Scope, visible_to


async def latest_rubric(session: AsyncSession, workspace_id: UUID) -> RubricVersion | None:
    return (
        await session.execute(
            select(RubricVersion)
            .where(RubricVersion.workspace_id == workspace_id)
            .order_by(RubricVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def snapshot_items_with_text(session: AsyncSession, snapshot_id: UUID) -> list[object]:
    """Job-level read: the snapshot's items with the chunk text they were built from."""
    from app.evidence.models import EvidenceChunk, EvidenceReference

    rows = await session.execute(
        select(
            EvidenceSnapshotItem.evidence_ref_id,
            EvidenceChunk.text,
            EvidenceReference.locator,
            EvidenceChunk.visibility,
            EvidenceSnapshotItem.source_version,
            EvidenceSnapshotItem.integration_of_earlier_work,
        )
        .join(EvidenceReference, EvidenceReference.id == EvidenceSnapshotItem.evidence_ref_id)
        .join(EvidenceChunk, EvidenceChunk.evidence_ref_id == EvidenceReference.id)
        .where(EvidenceSnapshotItem.snapshot_id == snapshot_id)
        .order_by(EvidenceChunk.source_time, EvidenceChunk.chunk_no)
    )
    return [
        type(
            "Item",
            (),
            {
                "evidence_ref_id": row[0],
                "text": row[1],
                "locator": row[2],
                "visibility": row[3],
                "source_version": row[4],
                "integration_of_earlier_work": row[5],
            },
        )()
        for row in rows
    ]


async def latest_assessment(
    session: AsyncSession, student_id: UUID, project_id: UUID, period_id: UUID
) -> AssessmentVersion | None:
    """Job-level read: the pipeline runs in the worker and has no Scope of its own."""
    return (
        await session.execute(
            select(AssessmentVersion)
            .where(
                AssessmentVersion.student_id == student_id,
                AssessmentVersion.project_id == project_id,
                AssessmentVersion.period_id == period_id,
            )
            .order_by(AssessmentVersion.version_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def next_version_no(
    session: AsyncSession, student_id: UUID, project_id: UUID, period_id: UUID
) -> int:
    current = (
        await session.execute(
            select(func.max(AssessmentVersion.version_no)).where(
                AssessmentVersion.student_id == student_id,
                AssessmentVersion.project_id == project_id,
                AssessmentVersion.period_id == period_id,
            )
        )
    ).scalar_one()
    return int(current or 0) + 1


async def get_assessment(
    session: AsyncSession, scope: Scope, assessment_id: UUID
) -> AssessmentVersion | None:
    return (
        await session.execute(
            select(AssessmentVersion).where(
                AssessmentVersion.id == assessment_id, visible_to(scope, AssessmentVersion)
            )
        )
    ).scalar_one_or_none()


async def list_assessments(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    period_id: UUID | None = None,
) -> list[AssessmentVersion]:
    statement = (
        select(AssessmentVersion)
        .where(visible_to(scope, AssessmentVersion))
        .order_by(AssessmentVersion.created_at.desc())
    )
    if student_id is not None:
        statement = statement.where(AssessmentVersion.student_id == student_id)
    if project_id is not None:
        statement = statement.where(AssessmentVersion.project_id == project_id)
    if period_id is not None:
        statement = statement.where(AssessmentVersion.period_id == period_id)
    return list((await session.execute(statement)).scalars().all())


async def versions_for_subject(
    session: AsyncSession, scope: Scope, student_id: UUID, project_id: UUID, period_id: UUID
) -> list[AssessmentVersion]:
    return list(
        (
            await session.execute(
                select(AssessmentVersion)
                .where(
                    AssessmentVersion.student_id == student_id,
                    AssessmentVersion.project_id == project_id,
                    AssessmentVersion.period_id == period_id,
                    visible_to(scope, AssessmentVersion),
                )
                .order_by(AssessmentVersion.version_no)
            )
        )
        .scalars()
        .all()
    )


async def approved_series(
    session: AsyncSession, scope: Scope, student_id: UUID, project_id: UUID
) -> list[AssessmentVersion]:
    """ASSESS-10: only approved versions appear in a trend."""
    return list(
        (
            await session.execute(
                select(AssessmentVersion)
                .join(
                    AssessmentReview,
                    AssessmentReview.assessment_version_id == AssessmentVersion.id,
                )
                .where(
                    AssessmentVersion.student_id == student_id,
                    AssessmentVersion.project_id == project_id,
                    AssessmentReview.state == ReviewState.APPROVED,
                    visible_to(scope, AssessmentVersion),
                )
                .order_by(AssessmentVersion.created_at)
            )
        )
        .scalars()
        .all()
    )


async def current_review(
    session: AsyncSession, scope: Scope, assessment_id: UUID
) -> AssessmentReview | None:
    return (
        await session.execute(
            select(AssessmentReview)
            .where(
                AssessmentReview.assessment_version_id == assessment_id,
                visible_to(scope, AssessmentReview),
            )
            .order_by(AssessmentReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def review_for(session: AsyncSession, assessment_id: UUID) -> AssessmentReview | None:
    """Job-level read used when rendering a version with its override applied."""
    return (
        await session.execute(
            select(AssessmentReview)
            .where(AssessmentReview.assessment_version_id == assessment_id)
            .order_by(AssessmentReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def supersede_other_reviews(
    session: AsyncSession,
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
    keep_assessment_id: UUID,
) -> None:
    """A newer draft supersedes an older draft; an approved version keeps standing until the
    professor approves its replacement (ASSESS-09, AC-03)."""
    older = select(AssessmentVersion.id).where(
        AssessmentVersion.student_id == student_id,
        AssessmentVersion.project_id == project_id,
        AssessmentVersion.period_id == period_id,
        AssessmentVersion.id != keep_assessment_id,
    )
    await session.execute(
        update(AssessmentReview)
        .where(
            AssessmentReview.assessment_version_id.in_(older),
            AssessmentReview.state == ReviewState.DRAFT,
        )
        .values(state=ReviewState.SUPERSEDED)
    )


async def latest_run(
    session: AsyncSession, student_id: UUID, project_id: UUID, period_id: UUID
) -> AnalysisRun | None:
    return (
        await session.execute(
            select(AnalysisRun)
            .where(
                AnalysisRun.student_id == student_id,
                AnalysisRun.project_id == project_id,
                AnalysisRun.period_id == period_id,
            )
            .order_by(AnalysisRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_feedback(session: AsyncSession, scope: Scope, assessment_id: UUID) -> list[Feedback]:
    return list(
        (
            await session.execute(
                select(Feedback)
                .where(
                    Feedback.subject_table == "assessment_versions",
                    Feedback.subject_id == assessment_id,
                    visible_to(scope, Feedback),
                )
                .order_by(Feedback.created_at)
            )
        )
        .scalars()
        .all()
    )


async def review_queue(
    session: AsyncSession, scope: Scope, *, as_of: datetime | None = None
) -> list[AssessmentVersion]:
    """UI-01: drafts waiting for the professor, oldest first — the order to work them in."""
    statement = (
        select(AssessmentVersion)
        .join(
            AssessmentReview,
            AssessmentReview.assessment_version_id == AssessmentVersion.id,
        )
        .where(
            visible_to(scope, AssessmentVersion),
            AssessmentReview.state == ReviewState.DRAFT,
        )
        .order_by(AssessmentVersion.created_at)
    )
    if as_of is not None:
        statement = statement.where(AssessmentVersion.created_at <= as_of)
    return list((await session.execute(statement)).scalars().all())


async def partial_runs(session: AsyncSession, scope: Scope) -> list[AnalysisRun]:
    """Runs that stopped short: a failed model step, or a budget that ran out (AC-13)."""
    return list(
        (
            await session.execute(
                select(AnalysisRun)
                .where(
                    AnalysisRun.workspace_id == scope.workspace_id,
                    AnalysisRun.state.in_(
                        [RunState.PARTIAL, RunState.FAILED, RunState.DELAYED_BUDGET]
                    ),
                )
                .order_by(AnalysisRun.started_at.desc())
            )
        )
        .scalars()
        .all()
    )
