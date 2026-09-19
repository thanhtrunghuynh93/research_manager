"""Facts about assessments: the queue, the trajectory, and the runs that stalled.

The trajectory is the one the specification is most careful about. A rubric change means the
numbers before and after are not the same measurement, so the series carries the rubric version of
every point and the fact says where the break is. Presenting them as one line would be the error
AC-10 exists to prevent.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.assistant.facts.base import Citation, Fact, FactQuery, display_name, fact
from app.identity import service as identity_service
from app.projects import service as projects_service


@fact("review_queue")
async def review_queue(session: AsyncSession, query: FactQuery) -> Fact:
    """UI-01: drafts waiting on the professor. A student's queue is empty by construction.

    The names travel with the rows, as they already do for `week_reports`. Without them the panel
    read "Draft for 01a0ad80" — and because these are UUIDv7 sharing a timestamp prefix, every
    draft on the screen showed the *same* eight characters, so three waiting assessments were
    indistinguishable from one another.
    """
    drafts = await assessment_service.review_queue(session, query.scope, as_of=query.as_of)

    titles: dict[UUID, str] = {}
    names: dict[UUID, str] = {}
    for draft in drafts:
        if draft.project_id not in titles:
            titles[draft.project_id] = await projects_service.project_title(
                session, draft.project_id
            )
        if draft.student_id not in names:
            names[draft.student_id] = await display_name(session, query, draft.student_id)

    return Fact(
        name="review_queue",
        label="Assessments awaiting review",
        value=len(drafts),
        as_of=query.as_of,
        rows=[
            {
                "assessment_id": str(draft.id),
                "student_id": str(draft.student_id),
                "student_name": names[draft.student_id],
                "project_id": str(draft.project_id),
                "project_title": titles[draft.project_id],
                "period_id": str(draft.period_id),
                "confidence": draft.confidence,
                "progress_index": draft.progress_index,
            }
            for draft in drafts
        ],
        citations=[
            Citation(
                source_kind="assessment_version",
                source_id=draft.id,
                locator=f"/review/{draft.id}",
                label=f"draft v{draft.version_no}",
            )
            for draft in drafts
        ],
        note="A draft is not published until the professor approves it.",
    )


@fact("progress_series")
async def progress_series(session: AsyncSession, query: FactQuery) -> Fact | None:
    """AC-10: each point carries its rubric, so a change reads as a break, not a decline."""
    if query.student_id is None or query.project_id is None:
        return None

    points = await assessment_service.progress_series(
        session, query.scope, student_id=query.student_id, project_id=query.project_id
    )
    points = [point for point in points if point.created_at <= query.as_of]
    if query.since is not None:
        points = [point for point in points if point.created_at >= query.since]

    rubric_versions = {str(point.rubric_version_id) for point in points if point.rubric_version_id}
    student = await identity_service.get_user(session, query.scope, query.student_id)
    project = await projects_service.get_project(session, query.scope, query.project_id)

    note = (
        "Only approved assessments appear. All points use one rubric version, so the trajectory "
        "is comparable."
        if len(rubric_versions) <= 1
        else (
            f"These points span {len(rubric_versions)} rubric versions. Scores produced under "
            "different rubrics are not directly comparable; treat the change as a break in the "
            "series rather than a rise or fall."
        )
    )

    return Fact(
        name="progress_series",
        label=f"{student.display_name} on {project.title}: approved assessments",
        value=len(points),
        as_of=query.as_of,
        rows=[
            {
                "period_id": str(point.period_id),
                "assessment_id": str(point.assessment_id),
                "progress_index": point.progress_index,
                "plan_completion": (
                    None if point.plan_completion is None else str(point.plan_completion)
                ),
                "confidence": point.confidence,
                "rubric_version_id": str(point.rubric_version_id),
                "created_at": point.created_at.isoformat(),
            }
            for point in points
        ],
        citations=[
            Citation(
                source_kind="assessment_version",
                source_id=point.assessment_id,
                locator=f"/review/{point.assessment_id}",
                label=f"assessment for period {point.period_id}",
            )
            for point in points
        ],
        note=note,
    )


@fact("stalled_analyses")
async def stalled_analyses(session: AsyncSession, query: FactQuery) -> Fact | None:
    """AC-13: a run that stopped short, and whether the cause was the model or the budget."""
    if not query.scope.is_prof:
        return None

    runs = await assessment_service.stalled_runs(session, query.scope)
    return Fact(
        name="stalled_analyses",
        label="Analyses that did not complete",
        value=len(runs),
        as_of=query.as_of,
        rows=[
            {
                "run_id": str(run.run_id),
                "student_id": str(run.student_id),
                "project_id": str(run.project_id),
                "period_id": str(run.period_id),
                "state": run.state,
                "reason": run.reason,
            }
            for run in runs
        ],
        note="Each of these is retryable; none of them changed a report or its timestamp.",
    )
