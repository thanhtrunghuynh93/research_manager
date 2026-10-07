"""AC-11 — A student's membership is removed | Subsequent access to the project's shared evidence
and documents is denied; the student's own historical records stay theirs.

Restated in 0.12. The scenario used to be about an assistant answer cached while the access was
valid; the assistant and its cache are gone (ADR 0023), and with them the access epoch that
invalidated it. What remains to prove is the ordinary half, which is the half that matters every
day: a membership is the entire grant to a project's ongoing work (AUTH-03), so ending it ends
every read that work is reached through — the evidence an assessment is built from, and the
documents the project shares (ADR 0018).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError, NotFoundError
from app.core.storage import InMemoryObjectStore, sha256_of
from app.core.types import Visibility
from app.evidence import service as evidence_service
from app.evidence.models import EvidenceSourceKind
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import artifacts
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance

# Shared with the project rather than owned by the student: a student's own report stays theirs
# after they leave, which is right. What must stop is reaching the project's shared material.
SHARED_TEXT = "Project protocol: the evaluation split is frozen at the September snapshot."
WINDOW = (datetime(2026, 9, 14, tzinfo=UTC), datetime(2026, 9, 21, tzinfo=UTC))


async def _project(
    db: AsyncSession, prof_scope: Scope, students: list[identity_models.User]
) -> tuple[object, object]:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Retrieval baselines", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    # Joined before today, so the membership is live now and ending it today actually ends it:
    # `left_on` is exclusive (architecture §5.2).
    for student in students:
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
        )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)
    return period, project


async def _end_membership_today(
    db: AsyncSession, prof_scope: Scope, project: object, student: identity_models.User
) -> None:
    from app.core.clock import now

    memberships = await projects_service.list_members(db, prof_scope, project.id)  # type: ignore[attr-defined]
    mine = next(one for one in memberships if one.student_id == student.id)
    await projects_service.end_membership(db, prof_scope, mine.id, left_on=now().date())


async def _shared_evidence(db: AsyncSession, scope: Scope, project_id: object) -> list[str]:
    hits = await evidence_service.search_evidence_window(
        db,
        scope,
        project_id=project_id,
        since=WINDOW[0],
        until=WINDOW[1],  # type: ignore[arg-type]
    )
    return [hit.text for hit in hits]


async def test_ac_11_the_projects_shared_evidence_is_denied_to_the_removed_student(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    _period, project = await _project(db, prof_scope, [student_a])
    await evidence_service.index_evidence(
        db,
        workspace_id=prof_scope.workspace_id,
        source_kind=EvidenceSourceKind.ARTIFACT_VERSION,
        source_id=project.id,  # type: ignore[attr-defined]
        source_version="1",
        text=SHARED_TEXT,
        visibility=Visibility.PROJECT_SHARED,
        project_id=project.id,  # type: ignore[attr-defined]
        source_time=datetime(2026, 9, 16, tzinfo=UTC),
    )
    before = await _shared_evidence(
        db,
        await identity_service.scope_for(db, student_a),
        project.id,  # type: ignore[attr-defined]
    )
    assert SHARED_TEXT in before, "the member could read the project's shared material"

    await _end_membership_today(db, prof_scope, project, student_a)

    after = await _shared_evidence(
        db,
        await identity_service.scope_for(db, student_a),
        project.id,  # type: ignore[attr-defined]
    )
    assert after == []


async def test_ac_11_the_projects_documents_are_denied_to_the_removed_student(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """A document another member shared with the project: readable while on it, not after."""
    store = InMemoryObjectStore()
    _period, project = await _project(db, prof_scope, [student_a, student_b])
    b_scope = await identity_service.scope_for(db, student_b)
    paper = b"# The protocol we are replicating"
    grant = await artifacts.request_upload(
        db,
        b_scope,
        project_id=project.id,  # type: ignore[attr-defined]
        filename="protocol.md",
        byte_size=len(paper),
        sha256=sha256_of(paper),
        store=store,
    )
    await store.put_bytes(grant.storage_key, paper, content_type=grant.content_type)
    await artifacts.confirm_upload(db, b_scope, grant.artifact_id, store=store)

    a_scope = await identity_service.scope_for(db, student_a)
    assert "protocol.md" in {row.filename for row in await artifacts.list_artifacts(db, a_scope)}

    await _end_membership_today(db, prof_scope, project, student_a)
    a_scope = await identity_service.scope_for(db, student_a)

    assert await artifacts.list_artifacts(db, a_scope) == []
    with pytest.raises((ForbiddenError, NotFoundError)):
        await artifacts.download_url(db, a_scope, grant.artifact_id, store=store)


async def test_ac_11_the_students_own_report_stays_theirs(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    """AUTH-03 preserves history: leaving ends the work, not the student's record of it."""
    period, project = await _project(db, prof_scope, [student_a])
    scope = await identity_service.scope_for(db, student_a)
    await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,  # type: ignore[attr-defined]
        entries=[
            {
                "project_id": project.id,  # type: ignore[attr-defined]
                "stage": "implementation",
                "work_performed": "Froze the evaluation split.",
            }
        ],
    )

    await _end_membership_today(db, prof_scope, project, student_a)

    after = await identity_service.scope_for(db, student_a)
    report = await reporting_service.get_report(db, after, period_id=period.id)  # type: ignore[attr-defined]
    assert report.current_version_id is not None
