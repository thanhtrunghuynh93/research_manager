"""AUTH-02: permission-filtered reads of indexed evidence.

The filter is part of the query, not a step after it: a chunk outside the caller's scope is never
read, so it cannot reach an assessment's snapshot or a citation in one (architecture §5.7). The
snapshot builder reads through the student's own scope (ASSESS-01), so what a student may see here
is exactly what an assessment of them may rest on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import models, service
from app.evidence.schemas import EvidenceHit
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from tests.factories import make_project

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


async def _read(
    db: AsyncSession, scope: Scope, project: object, *, since: datetime = WEEK - timedelta(days=1)
) -> list[EvidenceHit]:
    """Everything the caller may see on this project from `since` to a day after the week."""
    return await service.search_evidence_window(
        db,
        scope,
        project_id=project.id,  # type: ignore[attr-defined]
        since=since,
        until=WEEK + timedelta(days=1),
    )


async def _index(
    db: AsyncSession,
    scope: Scope,
    project: object,
    text: str,
    *,
    visibility: Visibility = Visibility.PROJECT_SHARED,
    owner_student_id: object = None,
    source_id: object = None,
    locator: str = "report entry",
) -> object:
    from uuid import uuid4

    return await service.index_evidence(
        db,
        workspace_id=scope.workspace_id,
        project_id=project.id,
        source_kind=models.EvidenceSourceKind.REPORT_ENTRY,
        source_id=source_id or uuid4(),
        source_version="1",
        locator=locator,
        text=text,
        visibility=visibility,
        owner_student_id=owner_student_id,
        source_time=WEEK,
    )


async def test_a_professor_reads_everything_on_the_project(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await make_project(db, prof_scope)
    await _index(db, prof_scope, project, "We reproduced the published baseline within one point.")
    await _index(db, prof_scope, project, "The dataset loader drops the final validation split.")

    hits = await _read(db, prof_scope, project)

    assert len(hits) == 2


async def test_a_student_never_sees_another_students_private_evidence(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    project = await make_project(db, prof_scope)
    for student in (student_a, student_b):
        await projects_service.add_member(db, prof_scope, project.id, student_id=student.id)
    await _index(
        db,
        prof_scope,
        project,
        "Student B private notes about the failing baseline.",
        visibility=Visibility.STUDENT_PRIVATE,
        owner_student_id=student_b.id,
    )

    scope = await identity_service.scope_for(db, student_a)
    assert await _read(db, scope, project) == []


async def test_a_student_retrieves_their_own_private_evidence(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await make_project(db, prof_scope)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await _index(
        db,
        prof_scope,
        project,
        "My own notes about the baseline experiment.",
        visibility=Visibility.STUDENT_PRIVATE,
        owner_student_id=student_a.id,
    )

    scope = await identity_service.scope_for(db, student_a)
    assert len(await _read(db, scope, project)) == 1


async def test_professor_only_material_never_reaches_a_student(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Professor-only material must never flow into what is assessed of, and released to, a student.
    project = await make_project(db, prof_scope)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await _index(
        db,
        prof_scope,
        project,
        "Supervision note: the baseline work is behind and needs a conversation.",
        visibility=Visibility.PROFESSOR_ONLY,
    )

    scope = await identity_service.scope_for(db, student_a)
    assert await _read(db, scope, project) == []
    assert len(await _read(db, prof_scope, project)) == 1


async def test_a_student_sees_nothing_from_a_project_they_left(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AUTH-03: removing a membership invalidates subsequent access, evidence included.
    project = await make_project(db, prof_scope)
    membership = await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id
    )
    await _index(db, prof_scope, project, "Shared notes on the baseline evaluation.")
    scope = await identity_service.scope_for(db, student_a)
    assert len(await _read(db, scope, project)) == 1

    await projects_service.end_membership(db, prof_scope, membership.id)

    after = await identity_service.scope_for(db, student_a)
    assert await _read(db, after, project) == []


async def test_a_read_is_scoped_to_one_project(db: AsyncSession, prof_scope: Scope) -> None:
    first = await make_project(db, prof_scope, title="Baseline")
    second = await make_project(db, prof_scope, title="Theory")
    await _index(db, prof_scope, first, "The baseline evaluation harness is complete.")
    await _index(db, prof_scope, second, "The baseline proof needs another lemma.")

    hits = await _read(db, prof_scope, second)

    assert len(hits) == 1
    assert "lemma" in hits[0].text


async def test_a_read_is_bounded_by_time(db: AsyncSession, prof_scope: Scope) -> None:
    project = await make_project(db, prof_scope)
    await service.index_evidence(
        db,
        workspace_id=prof_scope.workspace_id,
        project_id=project.id,
        source_kind=models.EvidenceSourceKind.REPORT_ENTRY,
        source_id=project.id,
        source_version="1",
        locator="old entry",
        text="An older note about the baseline.",
        visibility=Visibility.PROJECT_SHARED,
        source_time=WEEK - timedelta(days=30),
    )
    await _index(db, prof_scope, project, "A recent note about the baseline.")

    hits = await _read(db, prof_scope, project, since=WEEK - timedelta(days=1))

    assert len(hits) == 1
    assert "recent" in hits[0].text


async def test_a_hit_carries_everything_a_citation_needs(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # ASSESS-02: a citation names an authorized source at a stated version and location.
    project = await make_project(db, prof_scope)
    await _index(db, prof_scope, project, "The baseline reproduces.", locator="work_performed")

    [hit] = await _read(db, prof_scope, project)

    assert hit.source_kind is models.EvidenceSourceKind.REPORT_ENTRY
    assert hit.source_id is not None
    assert hit.source_version == "1"
    assert hit.locator.startswith("work_performed")
    assert hit.source_time == WEEK


async def test_reindexing_the_same_source_replaces_rather_than_duplicates(
    db: AsyncSession, prof_scope: Scope
) -> None:
    from uuid import uuid4

    project = await make_project(db, prof_scope)
    source_id = uuid4()
    await _index(
        db, prof_scope, project, "First version of the baseline note.", source_id=source_id
    )
    await _index(
        db, prof_scope, project, "Second version of the baseline note.", source_id=source_id
    )

    hits = await _read(db, prof_scope, project)

    assert len(hits) == 1
    assert "Second version" in hits[0].text


async def test_indexed_evidence_carries_its_visibility_label(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Requirements §9: explicit access labels on indexed evidence.
    project = await make_project(db, prof_scope)
    reference = await _index(
        db,
        prof_scope,
        project,
        "Private to the student.",
        visibility=Visibility.STUDENT_PRIVATE,
        owner_student_id=student_a.id,
    )

    assert reference.visibility is Visibility.STUDENT_PRIVATE
    assert reference.owner_student_id == student_a.id
    chunks = await service.chunks_for_reference(db, reference.id)
    assert chunks and all(chunk.visibility is Visibility.STUDENT_PRIVATE for chunk in chunks)
