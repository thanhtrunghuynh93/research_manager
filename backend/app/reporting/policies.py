"""Visibility predicates for reporting aggregates (AUTH-02, AC-02).

A project membership does not grant access to another student's report: reports are private to
their author and the professor (requirements §2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.reporting.models import (
    Artifact,
    CalendarConfig,
    ProjectReportEntry,
    ReportingObligation,
    ReportingPeriod,
    ReportVersion,
    RevisionRequest,
    WeeklyReport,
)


@register_policy(ReportingPeriod)
def period_visible_to(scope: Scope) -> ColumnElement[bool]:
    """The calendar is workspace-wide: everyone needs to know when their report is due."""
    return scope.within(ReportingPeriod.workspace_id)


@register_policy(CalendarConfig)
def calendar_visible_to(scope: Scope) -> ColumnElement[bool]:
    return scope.within(CalendarConfig.workspace_id)


@register_policy(ReportingObligation)
def obligation_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(ReportingObligation.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, ReportingObligation.student_id == scope.user_id)


@register_policy(WeeklyReport)
def report_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = scope.within(WeeklyReport.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, WeeklyReport.student_id == scope.user_id)


def _through_report(report_id: InstrumentedAttribute[UUID], scope: Scope) -> ColumnElement[bool]:
    """A version, entry, or request is visible exactly when its report is."""
    return report_id.in_(select(WeeklyReport.id).where(report_visible_to(scope)))


@register_policy(ReportVersion)
def version_visible_to(scope: Scope) -> ColumnElement[bool]:
    if scope.is_prof:
        return scope.within(ReportVersion.workspace_id)
    return and_(
        scope.within(ReportVersion.workspace_id),
        _through_report(ReportVersion.report_id, scope),
    )


@register_policy(ProjectReportEntry)
def entry_visible_to(scope: Scope) -> ColumnElement[bool]:
    if scope.is_prof:
        return scope.within(ProjectReportEntry.workspace_id)
    return and_(
        scope.within(ProjectReportEntry.workspace_id),
        ProjectReportEntry.report_version_id.in_(
            select(ReportVersion.id).where(version_visible_to(scope))
        ),
    )


@register_policy(RevisionRequest)
def revision_request_visible_to(scope: Scope) -> ColumnElement[bool]:
    if scope.is_prof:
        return scope.within(RevisionRequest.workspace_id)
    return and_(
        scope.within(RevisionRequest.workspace_id),
        _through_report(RevisionRequest.report_id, scope),
    )


@register_policy(Artifact)
def artifact_visible_to(scope: Scope) -> ColumnElement[bool]:
    """REP-04/AC-02: an attachment belongs to the student who attached it.

    Project membership is deliberately not enough for one. An attachment supports one student's
    report, and a report is private to its author and the professor (requirements §2); sharing the
    file more widely than the entry it belongs to would be a leak through the back door.

    **A project document is the exception, and it is a different thing wearing the same table**
    (PROJ-01 "shared resources", ADR 0018). It supports the project rather than anyone's week, so
    it is readable by whoever is on the project. The two are told apart by what they are *not*
    attached to: a report attachment always carries the period it was attached for — and an entry
    once the week is submitted — while a project document carries neither. Both columns are tested
    rather than one, because a draft week's attachment has no entry either, and keying on `entry_id`
    alone would have shared every unsubmitted file with the whole project.

    The widening is bounded by the same membership that already grants the project's plan,
    tasks, decisions and member list, so it adds a kind of record to that set rather
    than a new way in. What follows from it is what follows from all of them: a professor who marks
    a project open to joining is opening its documents too (ADR 0017).
    """
    same_workspace = scope.within(Artifact.workspace_id)
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        or_(
            Artifact.owner_student_id == scope.user_id,
            and_(
                Artifact.entry_id.is_(None),
                Artifact.period_id.is_(None),
                Artifact.project_id.in_(scope.project_ids),
            ),
        ),
    )
