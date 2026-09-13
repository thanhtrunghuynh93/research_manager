"""Building an export bundle (UI-06, requirements §11 "Portability").

Every record is read through the owning module's `service.py`. That is not indirection for its own
sake: it is the reason "export authorization must match interactive access" is true by construction
rather than by a reviewer remembering to check. A student's bundle is their own reports and their
own approved assessments, because those are the rows the same predicate returns on screen.

Two smaller decisions worth naming. Asking for a kind you may not export is refused rather than
answered with an empty list, because an empty list is a claim that there is nothing there. And a
bundle records the filters it was built with, so a partial export cannot later be mistaken for a
complete one.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ForbiddenError, ValidationError
from app.core.pagination import collect_all
from app.exports.schemas import SCHEMA_VERSION, Bundle
from app.projects import service as projects_service
from app.reporting import service as reporting_service

log = logging.getLogger(__name__)

KINDS: tuple[str, ...] = (
    "reports",
    "assessments",
    "projects",
    "obligations",
    "supervision_notes",
)
DEFAULT_KINDS: tuple[str, ...] = ("reports", "assessments", "projects")

# Kinds only the professor may ask for at all (QA-06).
PROFESSOR_ONLY: frozenset[str] = frozenset({"supervision_notes"})


async def build(
    session: AsyncSession,
    scope: Scope,
    *,
    kinds: Sequence[str] | None = None,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Bundle:
    wanted = tuple(kinds) if kinds else DEFAULT_KINDS
    unknown = [kind for kind in wanted if kind not in KINDS]
    if unknown:
        raise ValidationError(f"unknown export kind(s): {', '.join(sorted(unknown))}")

    refused = [kind for kind in wanted if kind in PROFESSOR_ONLY and not scope.is_prof]
    if refused:
        # Not an empty list: that would read as "there are none" (QA-06).
        raise ForbiddenError(f"not authorized to export: {', '.join(sorted(refused))}")

    bundle = Bundle(
        metadata={
            "schema_version": SCHEMA_VERSION,
            "generated_at": now().isoformat(),
            "generated_for": str(scope.user_id),
            "workspace_id": str(scope.workspace_id),
            "role": scope.role.value,
            "kinds": list(wanted),
            "filters": {
                "student_id": str(student_id) if student_id else None,
                "project_id": str(project_id) if project_id else None,
                "since": since.isoformat() if since else None,
                "until": until.isoformat() if until else None,
            },
            "note": (
                "Contains only records the requesting account may read interactively. A bundle is "
                "not a complete workspace export unless it was produced by the professor with no "
                "filters."
            ),
        }
    )

    builders = {
        "reports": _reports,
        "assessments": _assessments,
        "projects": _projects,
        "obligations": _obligations,
        "supervision_notes": _supervision_notes,
    }
    for kind in wanted:
        bundle.records[kind] = await builders[kind](
            session,
            scope,
            student_id=student_id,
            project_id=project_id,
            since=since,
            until=until,
        )
    return bundle


async def _reports(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[dict[str, Any]]:
    records = await reporting_service.submissions(
        session, scope, student_id=student_id, since=since, until=until
    )
    rows = []
    for record in records:
        version = await reporting_service.get_version(session, scope, record.version_id)
        entries = [
            {
                "entry_id": str(entry.id),
                "project_id": str(entry.project_id),
                "stage": str(entry.stage),
                "work_performed": entry.work_performed,
                "results": entry.results,
                "deviations": entry.deviations,
                "questions": entry.questions,
                "next_plan": entry.next_plan,
                "evidence_refs": entry.evidence_refs,
                "content_changed_in_version_id": str(entry.content_changed_in_version_id),
            }
            for entry in version.entries
            if project_id is None or entry.project_id == project_id
        ]
        if project_id is not None and not entries:
            continue
        rows.append(
            {
                "version_id": str(record.version_id),
                "report_id": str(record.report_id),
                "student_id": str(record.student_id),
                "period_id": str(record.period_id),
                "version_no": record.version_no,
                "submitted_at": record.submitted_at.isoformat(),
                "timing_status": record.timing_status,
                "local_start": record.local_start.isoformat(),
                "local_end": record.local_end.isoformat(),
                "deadline_utc": record.deadline_utc.isoformat(),
                "entries": entries,
            }
        )
    return rows


async def _assessments(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[dict[str, Any]]:
    rows = await assessment_service.list_assessments(
        session, scope, student_id=student_id, project_id=project_id
    )
    return [
        {
            "assessment_id": str(row.id),
            "student_id": str(row.student_id),
            "project_id": str(row.project_id),
            "period_id": str(row.period_id),
            "version_no": row.version_no,
            "report_version_id": str(row.report_version_id) if row.report_version_id else None,
            "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
            "rubric_version_id": str(row.rubric_version_id) if row.rubric_version_id else None,
            "ratings": row.ratings,
            "effective_ratings": row.effective_ratings,
            "progress_index": row.progress_index,
            "plan_completion": None if row.plan_completion is None else str(row.plan_completion),
            "coverage_pct": str(row.coverage_pct),
            "confidence": row.confidence,
            "confidence_reasons": row.confidence_reasons,
            "narrative": row.narrative,
            "model_name": row.model_name,
            "prompt_versions": row.prompt_versions,
            "review_state": str(row.review_state) if row.review_state else None,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
        if _within(row.created_at, since, until)
    ]


async def _projects(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[dict[str, Any]]:
    # Every project the caller may see: the bundle's own metadata asserts that a professor's
    # unfiltered export is complete, which the first page of two hundred is not (UI-06).
    projects = await collect_all(
        lambda cursor: projects_service.list_projects(session, scope, limit=200, cursor=cursor)
    )
    rows = []
    for project in projects:
        if project_id is not None and project.id != project_id:
            continue
        members = await projects_service.list_members(session, scope, project.id, include_past=True)
        rows.append(
            {
                "project_id": str(project.id),
                "title": project.title,
                "description": project.description,
                "research_questions": project.research_questions,
                "intended_contributions": project.intended_contributions,
                "stage": str(project.stage),
                "status": str(project.status),
                "start_on": project.start_on.isoformat() if project.start_on else None,
                "target_on": project.target_on.isoformat() if project.target_on else None,
                "venue_target": project.venue_target,
                "members": [
                    {
                        "student_id": str(member.student_id),
                        "responsibility": member.responsibility,
                        "joined_on": member.joined_on.isoformat(),
                        "left_on": member.left_on.isoformat() if member.left_on else None,
                    }
                    for member in members
                    if student_id is None or member.student_id == student_id
                ],
            }
        )
    return rows


async def _obligations(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[dict[str, Any]]:
    rows = []
    for period in await reporting_service.list_periods(session, scope):
        if not _within(period.start_utc, since, until):
            continue
        for obligation in await reporting_service.list_obligations(
            session, scope, period.id, student_id=student_id
        ):
            if project_id is not None and obligation.project_id != project_id:
                continue
            rows.append(
                {
                    "obligation_id": str(obligation.id),
                    "period_id": str(period.id),
                    "local_start": period.local_start.isoformat(),
                    "local_end": period.local_end.isoformat(),
                    "deadline_utc": period.deadline_utc.isoformat(),
                    "student_id": str(obligation.student_id),
                    "project_id": str(obligation.project_id),
                    "state": str(obligation.state),
                    "excuse_reason": obligation.excuse_reason,
                    "extension_until_utc": (
                        obligation.extension_until_utc.isoformat()
                        if obligation.extension_until_utc
                        else None
                    ),
                }
            )
    return rows


async def _supervision_notes(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None,
    project_id: UUID | None,
    since: datetime | None,
    until: datetime | None,
) -> list[dict[str, Any]]:
    notes = await assessment_service.list_supervision_notes(
        session, scope, student_id=student_id, project_id=project_id, since=since, until=until
    )
    return [
        {
            "note_id": str(note.id),
            "student_id": str(note.student_id) if note.student_id else None,
            "project_id": str(note.project_id) if note.project_id else None,
            "period_id": str(note.period_id) if note.period_id else None,
            "body": note.body,
            "created_at": note.created_at.isoformat(),
        }
        for note in notes
    ]


def _within(moment: datetime, since: datetime | None, until: datetime | None) -> bool:
    if since is not None and moment < since:
        return False
    return not (until is not None and moment > until)


# ------------------------------------------------------------------ renderings


# Flat columns for the spreadsheet form. Nested structures are deliberately absent: a CSV that
# embeds JSON in a cell is neither readable nor machine-readable, and the JSON bundle is right
# there for anything that needs the whole shape.
CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "assessments": (
        "assessment_id",
        "student_id",
        "project_id",
        "period_id",
        "version_no",
        "progress_index",
        "plan_completion",
        "coverage_pct",
        "confidence",
        "review_state",
        "published_at",
        "rubric_version_id",
        "model_name",
        "created_at",
    ),
    "reports": (
        "version_id",
        "student_id",
        "period_id",
        "version_no",
        "timing_status",
        "submitted_at",
        "local_start",
        "local_end",
    ),
    "obligations": (
        "obligation_id",
        "student_id",
        "project_id",
        "period_id",
        "state",
        "excuse_reason",
        "extension_until_utc",
        "deadline_utc",
    ),
    "projects": ("project_id", "title", "stage", "status", "start_on", "target_on"),
    "supervision_notes": ("note_id", "student_id", "project_id", "created_at"),
}


def to_csv(bundle: Bundle, kind: str) -> str:
    columns = CSV_COLUMNS.get(kind)
    if columns is None:
        raise ValidationError(f"{kind} has no tabular form; use the JSON bundle")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in bundle.records.get(kind, []):
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()
