"""Assessment use cases: snapshot, pipeline, review (ASSESS-01..10).

The shape of this module follows one commitment from the requirements: the model drafts, the
professor decides. So the pipeline produces a draft with its evidence and its uncertainty on show,
the arithmetic happens in metrics.py where it can be replayed, and nothing reaches a student until
a person approves it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import AIGateway, Budget, CallContext, RestrictedGateway
from app.ai.prompts.registry import load as load_prompt
from app.ai.schemas import ClaimList, ClaimVerdicts, RubricOutput
from app.assessment import metrics, policies, snapshot  # noqa: F401
from app.assessment import repository as repo
from app.assessment.metrics import (
    NOT_APPLICABLE,
    UNKNOWN,
    PlanItem,
    SourceStatus,
    confidence,
    coverage_pct,
    plan_completion,
    progress_index,
)
from app.assessment.models import (
    AnalysisRun,
    AssessmentReview,
    AssessmentVersion,
    EvidenceSnapshot,
    EvidenceSnapshotItem,
    Feedback,
    FeedbackKind,
    ReviewState,
    RubricVersion,
    RunState,
    SupervisionNote,
)
from app.assessment.schemas import (
    AssessmentOut,
    FeedbackOut,
    ReviewOut,
    SnapshotItemOut,
    SnapshotOut,
    TrendPoint,
)
from app.core.audit import write_audit
from app.core.authz import Scope
from app.core.clock import now
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.core.types import Visibility
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

log = logging.getLogger(__name__)

DEFAULT_DIMENSIONS: dict[str, Any] = {
    "progress": {"weight": 30, "label": "Progress toward agreed outcomes"},
    "learning": {"weight": 30, "label": "Research learning and reasoning"},
    "rigor": {"weight": 25, "label": "Rigor and evidence quality"},
    "artifacts": {"weight": 15, "label": "Usable research artifacts"},
}
PROMPT_VERSION = "v1"


# ------------------------------------------------------------------ rubric


async def ensure_rubric(session: AsyncSession, scope: Scope) -> RubricVersion:
    """The rubric in force, created on first use from the defaults in ASSESS-03."""
    existing = await repo.latest_rubric(session, scope.workspace_id)
    if existing is not None:
        return existing

    rubric = RubricVersion(
        workspace_id=scope.workspace_id,
        version=1,
        name="Default research rubric",
        dimensions=DEFAULT_DIMENSIONS,
        stage_applicability={},
        calculation_rules={"high_coverage": 90, "low_coverage": 70},
        created_by=scope.user_id,
    )
    session.add(rubric)
    await session.flush()
    return rubric


def _weights(rubric: RubricVersion) -> dict[str, Decimal]:
    return {
        name: Decimal(str(spec.get("weight", 0)))
        for name, spec in (rubric.dimensions or DEFAULT_DIMENSIONS).items()
    }


def _not_applicable(rubric: RubricVersion, stage: str) -> set[str]:
    """ASSESS-04: the only place a dimension may be excluded as not applicable."""
    return set((rubric.stage_applicability or {}).get(stage, []))


# ------------------------------------------------------------------ snapshot (ASSESS-01)


async def build_snapshot(
    session: AsyncSession, *, student_id: UUID, project_id: UUID, period_id: UUID
) -> SnapshotOut:
    period = await reporting_service.period_for_job(session, period_id)
    if period is None:
        raise NotFoundError("reporting period not found")
    student = await identity_service.contact_for_job(session, student_id)
    if student is None:
        raise NotFoundError("student not found")

    epoch = await identity_service.access_epoch(session, student.workspace_id)
    scope = snapshot.student_view(student_id, student.workspace_id, project_id, epoch)
    draft = await snapshot.collect(
        session,
        scope=scope,
        project_id=project_id,
        window_start=period.start_utc,
        window_end=period.end_utc,
    )

    row = EvidenceSnapshot(
        workspace_id=student.workspace_id,
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
        window_start_utc=period.start_utc,
        window_end_utc=period.end_utc,
        integration_lag_days=snapshot.INTEGRATION_LAG.days,
        item_count=len(draft.items),
        coverage_notes=draft.coverage_notes,
        access_epoch=epoch,
    )
    session.add(row)
    await session.flush()

    for item in draft.items:
        session.add(
            EvidenceSnapshotItem(
                snapshot_id=row.id,
                evidence_ref_id=item.evidence_ref_id,
                workspace_id=student.workspace_id,
                source_version=item.source_version,
                integration_of_earlier_work=item.integration_of_earlier_work,
            )
        )
    await session.flush()
    return SnapshotOut.model_validate(row)


async def snapshot_items(session: AsyncSession, snapshot_id: UUID) -> list[SnapshotItemOut]:
    return [
        SnapshotItemOut.model_validate(row)
        for row in await repo.snapshot_items_with_text(session, snapshot_id)
    ]


# ------------------------------------------------------------------ the pipeline (ASSESS-07/09)


async def run_pipeline(
    session: AsyncSession,
    *,
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
    report_version_id: UUID | None = None,
    gateway: AIGateway | None = None,
) -> AssessmentOut | None:
    """Produce a draft assessment, or None when there is nothing new to assess.

    Returns None when this entry's content has not changed since the version the current
    assessment already used: revising one project's entry must not re-assess another (AC-17).
    """
    student = await identity_service.contact_for_job(session, student_id)
    if student is None:
        raise NotFoundError("student not found")
    workspace_id = student.workspace_id
    system = Scope(
        workspace_id=workspace_id,
        user_id=student_id,
        role=student.role,
        project_ids=frozenset({project_id}),
        access_epoch=await identity_service.access_epoch(session, workspace_id),
    )

    entry = await reporting_service.entry_for_assessment(
        session, report_version_id=report_version_id, project_id=project_id
    )
    current = await repo.latest_assessment(session, student_id, project_id, period_id)
    if entry is not None and current is not None:
        if current.entry_id == entry.id or current.report_version_id == entry.changed_in_version_id:
            return None  # this entry's content has not moved since the last assessment

    rubric = await ensure_rubric(session, system)
    run = AnalysisRun(
        workspace_id=workspace_id,
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
        report_version_id=report_version_id,
        entry_id=entry.id if entry else None,
        rubric_version_id=rubric.id,
        state=RunState.RUNNING,
    )
    session.add(run)
    await session.flush()

    snapshot_row = await build_snapshot(
        session, student_id=student_id, project_id=project_id, period_id=period_id
    )
    run.snapshot_id = snapshot_row.id
    items = await snapshot_items(session, snapshot_row.id)
    evidence = [
        {"id": str(item.evidence_ref_id), "text": item.text, "locator": item.locator}
        for item in items
    ]

    project = await projects_service.get_project(session, system, project_id)
    active_gateway: AIGateway = (
        RestrictedGateway() if project.ai_restricted else (gateway or _default_gateway())
    )

    rubric_result, steps, prompt_versions = await _analyse(
        active_gateway,
        entry_text=entry.text if entry else "",
        evidence=evidence,
        rubric={"dimensions": rubric.dimensions or DEFAULT_DIMENSIONS},
        project_id=project_id,
        restricted=project.ai_restricted,
        context=_billing(session, workspace_id, project_id, student.email),
    )
    run.steps = steps
    run.prompt_versions = prompt_versions

    if rubric_result is None and not project.ai_restricted:
        # Three different reasons produce no draft, and the professor needs to tell them apart:
        # the money ran out, the model failed, or there was nothing to assess. Only the second is
        # a fault (requirements §11, AC-13).
        delayed = steps.get("delayed_budget")
        run.state = RunState.DELAYED_BUDGET if delayed else RunState.PARTIAL
        run.error_summary = (
            delayed if delayed else steps.get("error", "the model step did not complete")
        )
        run.finished_at = now()
        await session.flush()
        return None

    assessment = await _record_assessment(
        session,
        system=system,
        rubric=rubric,
        run=run,
        snapshot_id=snapshot_row.id,
        snapshot_item_ids={item.evidence_ref_id for item in items},
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
        report_version_id=report_version_id,
        entry=entry,
        output=rubric_result,
        restricted=project.ai_restricted,
        model_name=getattr(active_gateway, "model", "unknown"),
        prompt_versions=prompt_versions,
        source_status_extras=steps,
    )
    run.state = RunState.RESTRICTED if project.ai_restricted else RunState.COMPLETED
    run.finished_at = now()
    await session.flush()
    return assessment


def _default_gateway() -> AIGateway:
    from app.ai.gateway import current_gateway

    return current_gateway()


@dataclass(frozen=True, slots=True)
class _Billing:
    """Who pays for a call and whose work it is about.

    The session travels with it so a ledger row lands in the same transaction as the assessment it
    paid for, and `subject_email` is the one address redaction keeps (architecture §10).
    """

    session: AsyncSession
    workspace_id: UUID
    project_id: UUID
    subject_email: str | None


def _billing(
    session: AsyncSession, workspace_id: UUID, project_id: UUID, subject_email: str | None
) -> _Billing:
    return _Billing(
        session=session,
        workspace_id=workspace_id,
        project_id=project_id,
        subject_email=subject_email,
    )


async def _analyse(
    gateway: AIGateway,
    *,
    entry_text: str,
    evidence: list[dict[str, Any]],
    rubric: dict[str, Any],
    project_id: UUID,
    restricted: bool,
    context: _Billing,
) -> tuple[RubricOutput | None, dict[str, Any], dict[str, str]]:
    """Claims, then matching, then rating — each step recorded (architecture §9.1)."""
    steps: dict[str, Any] = {}
    prompt_versions: dict[str, str] = {}
    if restricted:
        steps["restricted"] = True
        return None, steps, prompt_versions

    claims = await _call(gateway, "extract_claims", {"entry": entry_text}, ClaimList, context)
    steps["extract_claims"] = "completed" if claims.ok else "failed"
    prompt_versions["extract_claims"] = claims.prompt_version
    if not claims.ok:
        _record_failure(steps, "extract_claims", claims)
        return None, steps, prompt_versions

    verdicts = await _call(
        gateway,
        "match_claims",
        {
            "claims": [claim.model_dump() for claim in claims.value.claims],
            "evidence": evidence,
        },
        ClaimVerdicts,
        context,
    )
    steps["match_claims"] = "completed" if verdicts.ok else "failed"
    prompt_versions["match_claims"] = verdicts.prompt_version
    if not verdicts.ok:
        _record_failure(steps, "match_claims", verdicts)
        return None, steps, prompt_versions

    rating = await _call(
        gateway,
        "rate_rubric",
        {
            "rubric": rubric,
            "entry": entry_text,
            "evidence": evidence,
            "verdicts": [verdict.model_dump() for verdict in verdicts.value.verdicts],
        },
        RubricOutput,
        context,
    )
    steps["rate_rubric"] = "completed" if rating.ok else "failed"
    prompt_versions["rate_rubric"] = rating.prompt_version
    if not rating.ok:
        _record_failure(steps, "rate_rubric", rating)
        return None, steps, prompt_versions

    unverifiable = sum(1 for verdict in verdicts.value.verdicts if verdict.status == "unverifiable")
    steps["unverifiable_claims"] = unverifiable
    steps["discrepancies"] = [
        verdict.model_dump() for verdict in verdicts.value.verdicts if verdict.status != "supported"
    ]
    return rating.value, steps, prompt_versions


def _record_failure(steps: dict[str, Any], step: str, result: Any) -> None:
    """A budget that ran out is not a failure of the model, and is recorded as itself."""
    if result.error == "delayed_budget":
        steps[step] = "delayed_budget"
        steps["delayed_budget"] = "; ".join(result.notes) or "the AI budget for this month is spent"
        return
    steps["error"] = f"{step}: {result.error}"


async def _call(
    gateway: AIGateway,
    prompt_id: str,
    inputs: dict[str, Any],
    schema: type[Any],
    billing: _Billing,
) -> Any:
    prompt = load_prompt(prompt_id, PROMPT_VERSION)
    return await gateway.complete_structured(
        prompt_id=prompt_id,
        inputs=inputs,
        schema=schema,
        budget=Budget(max_tokens=prompt.max_tokens),
        context=CallContext(
            prompt_id=prompt_id,
            prompt_version=prompt.version,
            project_id=billing.project_id,
            workspace_id=billing.workspace_id,
            session=billing.session,
            subject_email=billing.subject_email,
        ),
    )


def validate_output(output: RubricOutput, *, allowed_evidence_ids: set[UUID]) -> dict[str, Any]:
    """AC-07/AC-12: a citation that is not in the snapshot cannot survive.

    Any evidence id the model invented is dropped, and a rating that rested on one is downgraded to
    `unknown` with the reason recorded, because a rating whose support has gone is not a rating.
    """
    allowed = {str(value) for value in allowed_evidence_ids}
    validated: dict[str, Any] = {}

    for name, rating in output.dimensions.items():
        kept = [ref for ref in rating.evidence_ref_ids if ref in allowed]
        dropped = [ref for ref in rating.evidence_ref_ids if ref not in allowed]
        notes: list[str] = []
        value: Any = UNKNOWN if rating.rating == UNKNOWN else int(rating.rating)

        if dropped:
            notes.append(
                f"{len(dropped)} cited evidence id(s) were not in the snapshot and were dropped"
            )
            if not kept:
                notes.append("the rating was downgraded to unknown because its support was invalid")
                value = UNKNOWN
        validated[name] = {
            "rating": value,
            "rationale": rating.rationale,
            "evidence_ref_ids": kept,
            "validation_notes": notes,
        }
    return validated


async def _record_assessment(
    session: AsyncSession,
    *,
    system: Scope,
    rubric: RubricVersion,
    run: AnalysisRun,
    snapshot_id: UUID,
    snapshot_item_ids: set[UUID],
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
    report_version_id: UUID | None,
    entry: Any,
    output: RubricOutput | None,
    restricted: bool,
    model_name: str,
    prompt_versions: dict[str, str],
    source_status_extras: dict[str, Any],
) -> AssessmentOut:
    weights = _weights(rubric)
    stage = getattr(entry, "stage", "") or ""
    excluded = _not_applicable(rubric, stage)

    if output is None:
        # Restricted: the metrics still run, the narrative does not exist, the professor rates.
        ratings = {
            name: {
                "rating": NOT_APPLICABLE if name in excluded else UNKNOWN,
                "rationale": "not rated: this project does not send content to a model provider",
                "evidence_ref_ids": [],
                "validation_notes": [],
            }
            for name in weights
        }
        narrative: dict[str, Any] = {"limitations": ["Not rated — restricted"]}
    else:
        ratings = validate_output(output, allowed_evidence_ids=snapshot_item_ids)
        for name in excluded:
            if name in ratings:
                ratings[name]["rating"] = NOT_APPLICABLE
        narrative = {
            "accomplishments": output.accomplishments,
            "blockers": output.blockers,
            "discrepancies": source_status_extras.get("discrepancies", []),
            "limitations": output.limitations,
            "next_steps": output.next_steps,
            "discussion_agenda": output.discussion_agenda,
        }

    rating_values: dict[str, Any] = {name: value["rating"] for name, value in ratings.items()}
    index = progress_index(rating_values, weights)

    baseline = await projects_service.effective_baseline_for_student(
        session,
        workspace_id=system.workspace_id,
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
    )
    completion = plan_completion(
        [
            PlanItem(weight=Decimal(str(item.weight)), accepted_completion=Decimal(0))
            for item in (baseline.items if baseline else [])
        ]
        if baseline
        else None
    )

    sufficiency = {
        name: value["rating"] not in (UNKNOWN,)
        for name, value in ratings.items()
        if value["rating"] != NOT_APPLICABLE
    }
    coverage = coverage_pct(sufficiency, weights)
    level, reasons = confidence(
        coverage,
        SourceStatus(
            report_submitted=report_version_id is not None,
            baseline_available=baseline is not None,
            repository_fresh=await _repository_freshness(session, system, project_id),
            unverifiable_claims=int(source_status_extras.get("unverifiable_claims", 0)),
            extra_reasons=(
                ["this project is restricted from model processing"] if restricted else []
            ),
        ),
    )

    version_no = await repo.next_version_no(session, student_id, project_id, period_id)
    assessment = AssessmentVersion(
        workspace_id=system.workspace_id,
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
        version_no=version_no,
        report_version_id=report_version_id,
        entry_id=getattr(entry, "id", None),
        baseline_id=baseline.id if baseline else None,
        snapshot_id=snapshot_id,
        rubric_version_id=rubric.id,
        analysis_run_id=run.id,
        ratings=ratings,
        progress_index=index,
        plan_completion=completion,
        coverage_pct=coverage,
        confidence=level.value,
        confidence_reasons=reasons,
        narrative=narrative,
        reason="restricted" if restricted else "",
        model_name=model_name,
        prompt_versions=prompt_versions,
    )
    session.add(assessment)
    await session.flush()

    session.add(
        AssessmentReview(
            workspace_id=system.workspace_id,
            assessment_version_id=assessment.id,
            state=ReviewState.DRAFT,
        )
    )
    await repo.supersede_other_reviews(session, student_id, project_id, period_id, assessment.id)
    await session.flush()
    return await _assessment_out(session, assessment)


async def _repository_freshness(
    session: AsyncSession, scope: Scope, project_id: UUID
) -> bool | None:
    """None when the project has no repository, which is not a gap in evidence (ASSESS-06)."""
    from app.evidence import service as evidence_service

    repositories = await evidence_service.list_repositories(session, scope, project_id=project_id)
    if not repositories:
        return None
    for repository in repositories:
        status = await evidence_service.sync_status(session, scope, repository.id)
        if status is None or status.state.value in ("failed", "partial"):
            return False
    return True


# ------------------------------------------------------------------ review (ASSESS-08)


async def approve(
    session: AsyncSession,
    scope: Scope,
    assessment_id: UUID,
    *,
    override: dict[str, Any] | None = None,
    rationale: str | None = None,
) -> ReviewOut:
    """Publish one assessment to its student, optionally adjusting it with a recorded reason."""
    scope.require_prof()
    assessment = await repo.get_assessment(session, scope, assessment_id)
    if assessment is None:
        raise NotFoundError("assessment not found")
    if override and not rationale:
        raise ValidationError("an override requires a recorded reason")

    review = await repo.current_review(session, scope, assessment_id)
    if review is None:
        raise NotFoundError("assessment review not found")
    if review.state is ReviewState.APPROVED:
        return ReviewOut.model_validate(review)

    review.state = ReviewState.APPROVED
    review.reviewer_id = scope.user_id
    review.override = override
    review.rationale = rationale
    review.published_at = now()
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="assessment.approved",
        target_table="assessment_versions",
        target_id=assessment_id,
        after={"override": bool(override), "rationale": rationale},
    )
    await session.flush()
    return ReviewOut.model_validate(review)


async def withdraw(session: AsyncSession, scope: Scope, assessment_id: UUID) -> ReviewOut:
    scope.require_prof()
    review = await repo.current_review(session, scope, assessment_id)
    if review is None:
        raise NotFoundError("assessment review not found")
    review.state = ReviewState.WITHDRAWN
    review.reviewer_id = scope.user_id
    write_audit(
        session,
        workspace_id=scope.workspace_id,
        actor_id=scope.user_id,
        action="assessment.withdrawn",
        target_table="assessment_versions",
        target_id=assessment_id,
    )
    await session.flush()
    return ReviewOut.model_validate(review)


async def request_correction(
    session: AsyncSession,
    scope: Scope,
    assessment_id: UUID,
    *,
    body: str,
    evidence: list[Any] | None = None,
) -> FeedbackOut:
    """ASSESS-08: a student may contest an assessment and add evidence for their case."""
    assessment = await repo.get_assessment(session, scope, assessment_id)
    if assessment is None:
        raise NotFoundError("assessment not found")
    if not scope.is_prof and assessment.student_id != scope.user_id:
        raise ForbiddenError("only the student assessed may request a correction")

    feedback = Feedback(
        workspace_id=scope.workspace_id,
        subject_table="assessment_versions",
        subject_id=assessment_id,
        author_id=scope.user_id,
        recipient_id=None,
        kind=FeedbackKind.CORRECTION_REQUEST,
        visibility=Visibility.STUDENT_PRIVATE,
        body=body,
        evidence_refs=evidence or [],
    )
    session.add(feedback)
    await session.flush()
    return FeedbackOut.model_validate(feedback)


async def add_supervision_note(
    session: AsyncSession,
    scope: Scope,
    *,
    body: str,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    period_id: UUID | None = None,
) -> UUID:
    """QA-06: private to the professor, in its own table, never indexed."""
    scope.require_prof()
    note = SupervisionNote(
        workspace_id=scope.workspace_id,
        author_id=scope.user_id,
        student_id=student_id,
        project_id=project_id,
        period_id=period_id,
        body=body,
    )
    session.add(note)
    await session.flush()
    return note.id


# ------------------------------------------------------------------ reads


async def get_assessment(session: AsyncSession, scope: Scope, assessment_id: UUID) -> AssessmentOut:
    assessment = await repo.get_assessment(session, scope, assessment_id)
    if assessment is None:
        raise NotFoundError("assessment not found")
    return await _assessment_out(session, assessment)


async def list_assessments(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    period_id: UUID | None = None,
) -> list[AssessmentOut]:
    """A student sees only versions with an approved review (ASSESS-08)."""
    rows = await repo.list_assessments(
        session, scope, student_id=student_id, project_id=project_id, period_id=period_id
    )
    return [await _assessment_out(session, row) for row in rows]


async def list_versions(
    session: AsyncSession,
    scope: Scope,
    *,
    student_id: UUID,
    project_id: UUID,
    period_id: UUID,
) -> list[AssessmentOut]:
    rows = await repo.versions_for_subject(session, scope, student_id, project_id, period_id)
    return [await _assessment_out(session, row) for row in rows]


async def current_review(
    session: AsyncSession, scope: Scope, assessment_id: UUID
) -> ReviewOut | None:
    review = await repo.current_review(session, scope, assessment_id)
    return None if review is None else ReviewOut.model_validate(review)


async def list_feedback(
    session: AsyncSession, scope: Scope, assessment_id: UUID
) -> list[FeedbackOut]:
    rows = await repo.list_feedback(session, scope, assessment_id)
    return [FeedbackOut.model_validate(row) for row in rows]


async def latest_run(
    session: AsyncSession, *, student_id: UUID, project_id: UUID, period_id: UUID
) -> AnalysisRun | None:
    return await repo.latest_run(session, student_id, project_id, period_id)


async def review_queue(
    session: AsyncSession, scope: Scope, *, as_of: Any = None
) -> list[AssessmentOut]:
    """UI-01: the drafts waiting on the professor, oldest first."""
    rows = await repo.review_queue(session, scope, as_of=as_of)
    return [await _assessment_out(session, row) for row in rows]


@dataclass(frozen=True, slots=True)
class StalledRun:
    """A run that produced no draft, and the reason, so the cause is legible (AC-13)."""

    run_id: UUID
    student_id: UUID
    project_id: UUID
    period_id: UUID
    state: str
    reason: str
    started_at: Any


async def stalled_runs(session: AsyncSession, scope: Scope) -> list[StalledRun]:
    scope.require_prof()
    return [
        StalledRun(
            run_id=run.id,
            student_id=run.student_id,
            project_id=run.project_id,
            period_id=run.period_id,
            state=str(run.state),
            reason=run.error_summary or "",
            started_at=run.started_at,
        )
        for run in await repo.partial_runs(session, scope)
    ]


async def progress_series(
    session: AsyncSession, scope: Scope, *, student_id: UUID, project_id: UUID
) -> list[TrendPoint]:
    """ASSESS-10/AC-10: approved points, each labelled with the rubric that produced it."""
    rows = await repo.approved_series(session, scope, student_id, project_id)
    return [
        TrendPoint(
            period_id=row.period_id,
            assessment_id=row.id,
            progress_index=row.progress_index,
            plan_completion=row.plan_completion,
            confidence=row.confidence,
            rubric_version_id=row.rubric_version_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _assessment_out(session: AsyncSession, assessment: AssessmentVersion) -> AssessmentOut:
    """The stored version, plus what stands after any professor override (ASSESS-08)."""
    review = await repo.review_for(session, assessment.id)
    effective = dict(assessment.ratings)
    if review is not None and review.override:
        for name, patch in (review.override.get("ratings") or {}).items():
            effective[name] = {**effective.get(name, {}), **patch}

    out = AssessmentOut.model_validate(assessment)
    return out.model_copy(
        update={
            "effective_ratings": effective,
            "review_state": review.state if review else None,
            "published_at": review.published_at if review else None,
        }
    )
