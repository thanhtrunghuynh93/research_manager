"""Facts that were quietly answering the wrong thing, or nothing at all.

Each of these fails by omission, which is the failure mode the assistant is least able to show:
a dropped fact reads as "the records do not answer that", and a truncated list reads as an
absence rather than as a limit that was reached.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import router
from app.assistant.facts.base import FactQuery
from app.assistant.facts.members import members
from app.assistant.facts.sources import stale_repositories
from app.core.authz import Scope
from app.evidence import service as evidence_service
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service

pytestmark = pytest.mark.module

AS_OF = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)


async def _project_with_two_members(
    db: AsyncSession,
    prof_scope: Scope,
    first: identity_models.User,
    second: identity_models.User,
) -> object:
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    for student in (first, second):
        await projects_service.add_member(
            db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 1)
        )
    return project


async def test_a_student_can_ask_who_else_is_on_their_project(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    """PROJ-02 grants this; the fact asked identity for each co-member's row, which fails closed.

    `_compute_facts` catches the NotFoundError and drops the whole fact, so the student was told
    nothing in the records answered the question.
    """
    project = await _project_with_two_members(db, prof_scope, student_a, student_b)
    scope = await identity_service.scope_for(db, student_a)

    fact = await members(db, FactQuery(scope=scope, as_of=AS_OF, project_id=project.id))

    assert fact is not None
    assert fact.value == 2
    names = {row["display_name"] for row in fact.rows}
    assert names == {student_a.display_name, student_b.display_name}
    assert all(name for name in names), "a name, not a truncated id"


async def test_the_professor_sees_the_same_members(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    project = await _project_with_two_members(db, prof_scope, student_a, student_b)

    fact = await members(db, FactQuery(scope=prof_scope, as_of=AS_OF, project_id=project.id))

    assert fact is not None and fact.value == 2


async def test_stale_repositories_cites_the_stale_ones(db: AsyncSession, prof_scope: Scope) -> None:
    """Twenty citations to healthy repositories beside "one is stale" is worse than none."""
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline evaluation", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")

    healthy = await evidence_service.connect_repository(
        db,
        prof_scope,
        provider="github",
        external_id="1",
        full_name="lab/healthy",
        connector=FakeRepositoryConnector(),
    )
    stale = await evidence_service.connect_repository(
        db,
        prof_scope,
        provider="github",
        external_id="2",
        full_name="lab/stale",
        connector=FakeRepositoryConnector(),
    )
    for repository in (healthy, stale):
        await evidence_service.link_project(db, prof_scope, repository.id, project.id)
    # Only one has ever synced; the other has never run and is therefore stale.
    await evidence_service.sync_repository(
        db, prof_scope, healthy.id, connector=FakeRepositoryConnector()
    )

    fact = await stale_repositories(
        db, FactQuery(scope=prof_scope, as_of=datetime.now(UTC), project_id=project.id)
    )

    assert fact.value == 1
    assert [citation.label for citation in fact.citations] == ["lab/stale"]


async def test_a_student_past_the_first_page_is_still_found(
    db: AsyncSession, prof_scope: Scope, workspace: identity_models.Workspace
) -> None:
    """Entity resolution read one page of 200, so a later row simply did not exist.

    `_resolve_entities` then noted "no student matches" and the assistant answered about the whole
    workspace instead of asking who was meant — the failure `router` is written to prevent (QA-05).
    """
    from tests.factories import make_user

    for index in range(205):
        await make_user(
            db, workspace, email=f"bulk-{index}@example.edu", display_name=f"Bulk {index}"
        )
    needle = await make_user(db, workspace, email="trang@example.edu", display_name="Trang Nguyen")

    matches = await router._match_students(db, prof_scope, "Trang Nguyen")

    assert [row[0] for row in matches] == [needle.id]
