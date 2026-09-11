"""Visibility predicates for reporting aggregates (AUTH-02, AC-02).

A project membership does not grant access to another student's report: reports are private to
their author and the professor (requirements §2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

from app.core.authz import Scope, register_policy
from app.reporting.models import (
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
    return ReportingPeriod.workspace_id == scope.workspace_id


@register_policy(CalendarConfig)
def calendar_visible_to(scope: Scope) -> ColumnElement[bool]:
    return CalendarConfig.workspace_id == scope.workspace_id


@register_policy(ReportingObligation)
def obligation_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = ReportingObligation.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, ReportingObligation.student_id == scope.user_id)


@register_policy(WeeklyReport)
def report_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = WeeklyReport.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, WeeklyReport.student_id == scope.user_id)


def _through_report(report_id: InstrumentedAttribute[UUID], scope: Scope) -> ColumnElement[bool]:
    """A version, entry, or request is visible exactly when its report is."""
    return report_id.in_(select(WeeklyReport.id).where(report_visible_to(scope)))


@register_policy(ReportVersion)
def version_visible_to(scope: Scope) -> ColumnElement[bool]:
    if scope.is_prof:
        return ReportVersion.workspace_id == scope.workspace_id
    return and_(
        ReportVersion.workspace_id == scope.workspace_id,
        _through_report(ReportVersion.report_id, scope),
    )


@register_policy(ProjectReportEntry)
def entry_visible_to(scope: Scope) -> ColumnElement[bool]:
    if scope.is_prof:
        return ProjectReportEntry.workspace_id == scope.workspace_id
    return and_(
        ProjectReportEntry.workspace_id == scope.workspace_id,
        ProjectReportEntry.report_version_id.in_(
            select(ReportVersion.id).where(version_visible_to(scope))
        ),
    )


@register_policy(RevisionRequest)
def revision_request_visible_to(scope: Scope) -> ColumnElement[bool]:
    if scope.is_prof:
        return RevisionRequest.workspace_id == scope.workspace_id
    return and_(
        RevisionRequest.workspace_id == scope.workspace_id,
        _through_report(RevisionRequest.report_id, scope),
    )
