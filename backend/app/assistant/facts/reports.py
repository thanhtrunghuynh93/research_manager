"""Facts read out of submitted report entries: what was done, and what is in the way.

These are still facts rather than synthesis: the text is the student's own and is quoted, not
summarised, so a blocker the assistant reports is a blocker the student wrote down. Turning the
week's entries into a narrative is the generation step's job, and it happens later and separately.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.facts.base import Citation, Fact, FactQuery, fact, report_locator
from app.reporting import service as reporting_service


@fact("blockers")
async def blockers(session: AsyncSession, query: FactQuery) -> Fact:
    """QA-01: what the student said is in the way, dated, and left in their words."""
    entries = await reporting_service.entries_in_range(
        session,
        query.scope,
        student_id=query.student_id,
        project_id=query.project_id,
        since=query.since,
        until=query.until,
        as_of=query.as_of,
    )
    rows = [
        {
            "entry_id": str(entry.entry_id),
            "student_id": str(entry.student_id),
            "project_id": str(entry.project_id),
            "period_id": str(entry.period_id),
            "submitted_at": entry.submitted_at.isoformat(),
            "deviations": entry.deviations,
            "questions": entry.questions,
        }
        for entry in entries
        if entry.deviations.strip() or entry.questions.strip()
    ]
    return Fact(
        name="blockers",
        label="Reported blockers and questions",
        value=len(rows),
        as_of=query.as_of,
        rows=rows,
        citations=[
            Citation(
                source_kind="report_entry",
                source_id=entry.entry_id,
                source_version=str(entry.version_id),
                locator=report_locator(
                    query.scope,
                    student_id=entry.student_id,
                    period_id=entry.period_id,
                    project_id=entry.project_id,
                ),
                label=f"entry submitted {entry.submitted_at.date()}",
            )
            for entry in entries
            if entry.deviations.strip() or entry.questions.strip()
        ],
        note="Quoted from the student's own entry. A blocker recorded here is a report, not a "
        "verified state of the world.",
    )


@fact("submissions")
async def submissions(session: AsyncSession, query: FactQuery) -> Fact:
    """Which weeks were submitted, when, and with what timing (REP-05)."""
    records = await reporting_service.submissions(
        session,
        query.scope,
        student_id=query.student_id,
        since=query.since,
        until=query.until,
        as_of=query.as_of,
    )
    return Fact(
        name="submissions",
        label="Submitted report versions",
        value=len(records),
        as_of=query.as_of,
        rows=[
            {
                "version_id": str(record.version_id),
                "student_id": str(record.student_id),
                "period_id": str(record.period_id),
                "version_no": record.version_no,
                "submitted_at": record.submitted_at.isoformat(),
                "timing_status": record.timing_status,
                "local_start": record.local_start.isoformat(),
                "local_end": record.local_end.isoformat(),
            }
            for record in records
        ],
        citations=[
            Citation(
                source_kind="report_version",
                source_id=record.version_id,
                source_version=str(record.version_no),
                locator=report_locator(
                    query.scope, student_id=record.student_id, period_id=record.period_id
                ),
                label=f"week of {record.local_start}, version {record.version_no}",
            )
            for record in records
        ],
    )


@fact("work_this_week")
async def work_this_week(session: AsyncSession, query: FactQuery) -> Fact:
    """The entries themselves, which is what "what did X accomplish?" is grounded in (QA-01)."""
    entries = await reporting_service.entries_in_range(
        session,
        query.scope,
        student_id=query.student_id,
        project_id=query.project_id,
        since=query.since,
        until=query.until,
        as_of=query.as_of,
    )
    return Fact(
        name="work_this_week",
        label="Reported work",
        value=len(entries),
        as_of=query.as_of,
        rows=[
            {
                "entry_id": str(entry.entry_id),
                "student_id": str(entry.student_id),
                "project_id": str(entry.project_id),
                "period_id": str(entry.period_id),
                "stage": entry.stage,
                "work_performed": entry.work_performed,
                "results": entry.results,
                "submitted_at": entry.submitted_at.isoformat(),
            }
            for entry in entries
        ],
        citations=[
            Citation(
                source_kind="report_entry",
                source_id=entry.entry_id,
                source_version=str(entry.version_id),
                locator=report_locator(
                    query.scope,
                    student_id=entry.student_id,
                    period_id=entry.period_id,
                    project_id=entry.project_id,
                ),
                label=f"entry submitted {entry.submitted_at.date()}",
            )
            for entry in entries
        ],
        note="What the student reported. Whether the evidence supports it is a separate question.",
    )
