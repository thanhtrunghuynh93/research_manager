"""Queries over the assessment tables. Every read on behalf of a caller applies `visible_to`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.assessment.models import (
    AnalysisRun,
    AssessmentReview,
    AssessmentVersion,
    EvidenceSnapshotItem,
    Feedback,
    ReviewState,
    RubricVersion,
    RunState,
    SupervisionNote,
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


async def rubric_by_id(session: AsyncSession, rubric_id: UUID | None) -> RubricVersion | None:
    """The rubric that produced one assessment, not whichever is latest (ASSESS-10, AC-10).

    A number is only meaningful against the measure it was computed with, so recomputing an index
    after an override has to use the same weights the draft used. `session.get` rather than a
    `select` because a list of assessments is usually a list under one rubric, and the identity
    map then answers every call after the first without another round trip.
    """
    if rubric_id is None:
        return None
    return await session.get(RubricVersion, rubric_id)


async def reviews_for(
    session: AsyncSession, assessment_ids: Sequence[UUID]
) -> dict[UUID, AssessmentReview]:
    """The newest review of each of these assessments, in one query rather than one per row."""
    if not assessment_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(AssessmentReview)
                .where(AssessmentReview.assessment_version_id.in_(list(assessment_ids)))
                .order_by(AssessmentReview.created_at)
            )
        )
        .scalars()
        .all()
    )
    # Ascending, so the last write for an id wins and each entry is that id's newest review —
    # the same choice `review_for` makes for a single assessment.
    return {row.assessment_version_id: row for row in rows}


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
    """Runs that stopped short and have not since been redone (AC-13).

    A retry does not repair the old row, it writes a new one — so without the second condition
    this list is an append-only log presented to the professor as a worklist. Retrying thirteen
    stalled runs would have left all thirteen on the overview for ever, beside whatever the
    retries produced, and the remedy would have looked exactly like a failure.

    Superseded means a *later* run for the same week, student and project got somewhere: either it
    completed, or it was refused because the project restricts what may reach a model, which is an
    answer rather than a stall.
    """
    later = aliased(AnalysisRun)
    redone = (
        select(later.id)
        .where(
            later.workspace_id == AnalysisRun.workspace_id,
            later.student_id == AnalysisRun.student_id,
            later.project_id == AnalysisRun.project_id,
            later.period_id == AnalysisRun.period_id,
            later.started_at > AnalysisRun.started_at,
            later.state.in_([RunState.COMPLETED, RunState.RESTRICTED]),
        )
        .exists()
    )
    return list(
        (
            await session.execute(
                select(AnalysisRun)
                .where(
                    AnalysisRun.workspace_id == scope.workspace_id,
                    AnalysisRun.state.in_(
                        [RunState.PARTIAL, RunState.FAILED, RunState.DELAYED_BUDGET]
                    ),
                    ~redone,
                )
                .order_by(AnalysisRun.started_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def list_supervision_notes(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[SupervisionNote]:
    """QA-06: professor-only by construction. The caller checks the role before asking."""
    statement = (
        select(SupervisionNote)
        .where(SupervisionNote.workspace_id == scope.workspace_id)
        .order_by(SupervisionNote.created_at.desc())
    )
    if student_id is not None:
        statement = statement.where(SupervisionNote.student_id == student_id)
    if project_id is not None:
        statement = statement.where(SupervisionNote.project_id == project_id)
    if since is not None:
        statement = statement.where(SupervisionNote.created_at >= since)
    if until is not None:
        statement = statement.where(SupervisionNote.created_at <= until)
    return list((await session.execute(statement)).scalars().all())
