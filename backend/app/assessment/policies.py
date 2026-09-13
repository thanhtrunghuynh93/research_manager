"""Visibility predicates for assessment aggregates (AUTH-02, ASSESS-08, QA-06)."""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.sql import ColumnElement

from app.assessment.models import (
    AnalysisRun,
    AssessmentReview,
    AssessmentVersion,
    EvidenceSnapshot,
    Feedback,
    ReviewState,
    RubricVersion,
    SupervisionNote,
)
from app.core.authz import Scope, register_policy


@register_policy(AssessmentVersion)
def assessment_visible_to(scope: Scope) -> ColumnElement[bool]:
    """A student sees their own assessments, and only once a review has approved them."""
    same_workspace = AssessmentVersion.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        AssessmentVersion.student_id == scope.user_id,
        AssessmentVersion.id.in_(
            select(AssessmentReview.assessment_version_id).where(
                AssessmentReview.state == ReviewState.APPROVED
            )
        ),
    )


@register_policy(AssessmentReview)
def review_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = AssessmentReview.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        AssessmentReview.assessment_version_id.in_(
            select(AssessmentVersion.id).where(assessment_visible_to(scope))
        ),
    )


@register_policy(EvidenceSnapshot)
def snapshot_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = EvidenceSnapshot.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, EvidenceSnapshot.student_id == scope.user_id)


@register_policy(AnalysisRun)
def run_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = AnalysisRun.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(same_workspace, AnalysisRun.student_id == scope.user_id)


@register_policy(RubricVersion)
def rubric_visible_to(scope: Scope) -> ColumnElement[bool]:
    """The rubric is workspace-wide: a student is entitled to know what they are assessed on."""
    return RubricVersion.workspace_id == scope.workspace_id


@register_policy(Feedback)
def feedback_visible_to(scope: Scope) -> ColumnElement[bool]:
    same_workspace = Feedback.workspace_id == scope.workspace_id
    if scope.is_prof:
        return same_workspace
    return and_(
        same_workspace,
        Feedback.visibility != "professor_only",
        (Feedback.author_id == scope.user_id) | (Feedback.recipient_id == scope.user_id),
    )


@register_policy(SupervisionNote)
def supervision_note_visible_to(scope: Scope) -> ColumnElement[bool]:
    """QA-06: never a student, under any condition."""
    if scope.is_prof:
        return SupervisionNote.workspace_id == scope.workspace_id
    return SupervisionNote.id.is_(None)
