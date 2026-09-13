"""AUTH-02/QA-06: permission-filtered retrieval over indexed evidence.

The filter is part of the query, not a step after it: a chunk outside the caller's scope is never
scored, so it cannot leak through a ranking, a snippet, or a citation (architecture §5.7).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.types import Visibility
from app.evidence import models, service
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


async def _project(db: AsyncSession, scope: Scope, title: str = "Baseline") -> object:
    project = await projects_service.create_project(db, scope, title=title, stage="implementation")
    await projects_service.update_project(db, scope, project.id, status="active")
    return project


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


async def test_a_professor_retrieves_what_matches(db: AsyncSession, prof_scope: Scope) -> None:
    project = await _project(db, prof_scope)
    await _index(db, prof_scope, project, "We reproduced the published baseline within one point.")
    await _index(db, prof_scope, project, "The dataset loader drops the final validation split.")

    hits = await service.search_evidence(db, prof_scope, query="baseline")

    assert hits
    assert "baseline" in hits[0].text.lower()


async def test_a_student_never_sees_another_students_private_evidence(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # QA-06: authorization is applied before retrieval, not after generation.
    project = await _project(db, prof_scope)
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
    hits = await service.search_evidence(db, scope, query="baseline")

    assert hits == []


async def test_a_student_retrieves_their_own_private_evidence(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    project = await _project(db, prof_scope)
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
    hits = await service.search_evidence(db, scope, query="baseline")

    assert len(hits) == 1


async def test_professor_only_material_never_reaches_a_student(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # QA-06: private supervision material must never flow into a student-facing answer.
    project = await _project(db, prof_scope)
    await projects_service.add_member(db, prof_scope, project.id, student_id=student_a.id)
    await _index(
        db,
        prof_scope,
        project,
        "Supervision note: the baseline work is behind and needs a conversation.",
        visibility=Visibility.PROFESSOR_ONLY,
    )

    scope = await identity_service.scope_for(db, student_a)
    assert await service.search_evidence(db, scope, query="baseline") == []
    assert len(await service.search_evidence(db, prof_scope, query="baseline")) == 1


async def test_a_student_sees_nothing_from_a_project_they_left(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AUTH-03: removing a membership invalidates subsequent access, retrieval included.
    project = await _project(db, prof_scope)
    membership = await projects_service.add_member(
        db, prof_scope, project.id, student_id=student_a.id
    )
    await _index(db, prof_scope, project, "Shared notes on the baseline evaluation.")
    scope = await identity_service.scope_for(db, student_a)
    assert len(await service.search_evidence(db, scope, query="baseline")) == 1

    await projects_service.end_membership(db, prof_scope, membership.id)

    after = await identity_service.scope_for(db, student_a)
    assert await service.search_evidence(db, after, query="baseline") == []


async def test_retrieval_can_be_scoped_to_one_project(db: AsyncSession, prof_scope: Scope) -> None:
    first = await _project(db, prof_scope, title="Baseline")
    second = await _project(db, prof_scope, title="Theory")
    await _index(db, prof_scope, first, "The baseline evaluation harness is complete.")
    await _index(db, prof_scope, second, "The baseline proof needs another lemma.")

    hits = await service.search_evidence(db, prof_scope, query="baseline", project_id=second.id)

    assert len(hits) == 1
    assert "lemma" in hits[0].text


async def test_retrieval_can_be_bounded_by_time(db: AsyncSession, prof_scope: Scope) -> None:
    from datetime import timedelta

    project = await _project(db, prof_scope)
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

    hits = await service.search_evidence(
        db, prof_scope, query="baseline", since=WEEK - timedelta(days=1)
    )

    assert len(hits) == 1
    assert "recent" in hits[0].text


async def test_a_hit_carries_everything_a_citation_needs(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # QA-03: a citation opens an authorized source at a stated version and location.
    project = await _project(db, prof_scope)
    await _index(db, prof_scope, project, "The baseline reproduces.", locator="work_performed")

    [hit] = await service.search_evidence(db, prof_scope, query="baseline")

    assert hit.source_kind is models.EvidenceSourceKind.REPORT_ENTRY
    assert hit.source_id is not None
    assert hit.source_version == "1"
    assert hit.locator.startswith("work_performed")
    assert hit.source_time == WEEK


async def test_reindexing_the_same_source_replaces_rather_than_duplicates(
    db: AsyncSession, prof_scope: Scope
) -> None:
    from uuid import uuid4

    project = await _project(db, prof_scope)
    source_id = uuid4()
    await _index(
        db, prof_scope, project, "First version of the baseline note.", source_id=source_id
    )
    await _index(
        db, prof_scope, project, "Second version of the baseline note.", source_id=source_id
    )

    hits = await service.search_evidence(db, prof_scope, query="baseline")

    assert len(hits) == 1
    assert "Second version" in hits[0].text


async def test_a_semantic_query_finds_a_chunk_with_no_shared_words(
    db: AsyncSession, prof_scope: Scope
) -> None:
    """The vector half of the hybrid must contribute, not just the keyword half.

    With the deterministic embedder a vector is a hash, so the honest check is that an exact
    restatement retrieves through the vector path when the lexical query is empty.
    """
    project = await _project(db, prof_scope)
    text = "We reproduced the published baseline within one point on the public split."
    await _index(db, prof_scope, project, text)
    await _index(db, prof_scope, project, "Unrelated notes on meeting scheduling.")

    hits = await service.search_evidence(db, prof_scope, query=text, mode="semantic")

    assert hits
    assert hits[0].text.startswith("We reproduced")


async def test_an_empty_query_returns_nothing_rather_than_everything(
    db: AsyncSession, prof_scope: Scope
) -> None:
    project = await _project(db, prof_scope)
    await _index(db, prof_scope, project, "Something about the baseline.")

    assert await service.search_evidence(db, prof_scope, query="   ") == []


async def test_indexed_evidence_carries_its_visibility_label(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # Requirements §9: explicit access labels on indexed evidence.
    project = await _project(db, prof_scope)
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
