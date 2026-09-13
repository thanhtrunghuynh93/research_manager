"""The weekly package: calendar, obligations, drafts, submission, and revisions (REP-01..06)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import IdempotencyKeyDep, ProfScopeDep, ScopeDep, SessionDep
from app.reporting import service
from app.reporting.schemas import (
    CalendarConfigIn,
    CalendarConfigOut,
    DraftIn,
    ExcuseIn,
    ExtensionIn,
    ObligationOut,
    PeriodOut,
    ReportOut,
    RevisionRequestIn,
    RevisionRequestOut,
    SubmitIn,
    VersionOut,
)

router = APIRouter(tags=["reporting"])


@router.put("/calendar", summary="Configure the reporting calendar")
async def configure_calendar(
    payload: CalendarConfigIn, scope: ProfScopeDep, session: SessionDep
) -> CalendarConfigOut:
    return await service.configure_calendar(
        session,
        scope,
        timezone=payload.timezone,
        meeting_weekday=payload.meeting_weekday,
        week_start_weekday=payload.week_start_weekday,
        grace_minutes=payload.grace_minutes,
        effective_from=payload.effective_from,
    )


@router.get("/periods", summary="List reporting periods")
async def list_periods(
    scope: ScopeDep, session: SessionDep, through: date | None = None
) -> list[PeriodOut]:
    return await service.list_periods(session, scope, through=through)


@router.post("/periods/ensure", summary="Materialise periods up to a date")
async def ensure_periods(
    scope: ProfScopeDep, session: SessionDep, through: date | None = None
) -> list[PeriodOut]:
    return await service.ensure_periods(session, scope, through=through)


@router.get("/periods/{period_id}/obligations", summary="Who owes a report this period")
async def list_obligations(
    period_id: UUID, scope: ScopeDep, session: SessionDep, student_id: UUID | None = None
) -> list[ObligationOut]:
    return await service.list_obligations(session, scope, period_id, student_id=student_id)


@router.post("/periods/{period_id}/obligations/ensure", summary="Derive obligations")
async def ensure_obligations(
    period_id: UUID, scope: ProfScopeDep, session: SessionDep
) -> list[ObligationOut]:
    return await service.ensure_obligations(session, scope, period_id)


@router.post("/obligations/{obligation_id}/excuse", summary="Excuse an obligation")
async def excuse_obligation(
    obligation_id: UUID, payload: ExcuseIn, scope: ProfScopeDep, session: SessionDep
) -> ObligationOut:
    return await service.excuse_obligation(session, scope, obligation_id, reason=payload.reason)


@router.post("/obligations/{obligation_id}/extend", summary="Extend one obligation's deadline")
async def extend_obligation(
    obligation_id: UUID, payload: ExtensionIn, scope: ProfScopeDep, session: SessionDep
) -> ObligationOut:
    return await service.extend_obligation(
        session, scope, obligation_id, until=payload.until, reason=payload.reason
    )


@router.get("/periods/{period_id}/report", summary="Read a weekly report")
async def get_report(
    period_id: UUID, scope: ScopeDep, session: SessionDep, student_id: UUID | None = None
) -> ReportOut:
    return await service.get_report(session, scope, period_id=period_id, student_id=student_id)


@router.patch("/periods/{period_id}/report/draft", summary="Autosave the weekly draft")
async def save_draft(
    period_id: UUID, payload: DraftIn, scope: ScopeDep, session: SessionDep
) -> ReportOut:
    return await service.save_draft(session, scope, period_id=period_id, content=payload.content)


@router.post(
    "/periods/{period_id}/report/submit",
    status_code=status.HTTP_201_CREATED,
    summary="Submit the weekly package",
)
async def submit_report(
    period_id: UUID,
    payload: SubmitIn,
    scope: ScopeDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyDep,
) -> VersionOut:
    """A repeated submission with the same Idempotency-Key returns the version already written."""
    return await service.submit_report(
        session,
        scope,
        period_id=period_id,
        entries=[entry.model_dump() for entry in payload.entries],
        idempotency_key=idempotency_key,
    )


@router.get("/report-versions/{version_id}", summary="Read one submitted version")
async def get_version(version_id: UUID, scope: ScopeDep, session: SessionDep) -> VersionOut:
    return await service.get_version(session, scope, version_id)


@router.post(
    "/reports/{report_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    summary="Request a revision of one project entry",
)
async def request_revision(
    report_id: UUID, payload: RevisionRequestIn, scope: ProfScopeDep, session: SessionDep
) -> RevisionRequestOut:
    return await service.request_revision(
        session, scope, report_id=report_id, project_id=payload.project_id, reason=payload.reason
    )


@router.get("/reports/{report_id}/revisions", summary="Outstanding revision requests")
async def list_revision_requests(
    report_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[RevisionRequestOut]:
    return await service.list_revision_requests(session, scope, report_id=report_id)


@router.post("/reports/{report_id}/reviewed", summary="Mark a report reviewed")
async def mark_reviewed(report_id: UUID, scope: ProfScopeDep, session: SessionDep) -> ReportOut:
    return await service.mark_reviewed(session, scope, report_id=report_id)
