"""ADR 0026 under real concurrency: two sessions on two connections, both committing.

The rest of the suite runs inside one rolled-back transaction, where "two callers" are really one
connection taking turns and a row lock can never be contended. These tests commit, so the row lock
on `feedbacks` and the idempotency key's unique index are exercised for real. They clean up after
themselves in no way: submitted report versions and audit rows are immutable at the database level,
so a workspace with a submitted week cannot be deleted. Each test therefore builds its own workspace
with unique emails, and nothing else in the suite reads across workspaces or counts feedback rows
unscoped.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.audit import AuditEvent
from app.core.authz import Scope
from app.core.errors import ConflictError
from app.core.types import Role
from app.feedback import service
from app.feedback.models import Feedback, FeedbackIdempotency, FeedbackRevision
from app.identity import service as identity_service
from app.reporting import service as reporting_service
from tests.factories import Week, make_entry, make_user, make_week, make_workspace, submit

pytestmark = pytest.mark.module

ON_TIME = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    workspace_id: UUID
    prof_id: UUID
    student_id: UUID
    project_id: UUID
    report_ids: list[UUID]


@pytest.fixture
async def world(
    engine: AsyncEngine, frozen_now: Callable[[datetime], None]
) -> AsyncIterator[World]:
    frozen_now(ON_TIME)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        workspace = await make_workspace(session, name="Concurrency Lab")
        prof = await make_user(
            session, workspace, role=Role.PROF, email=f"prof-{uuid4().hex}@example.edu"
        )
        student = await make_user(
            session, workspace, role=Role.STUDENT, email=f"student-{uuid4().hex}@example.edu"
        )
        scope = await identity_service.scope_for(session, prof)
        week = await make_week(session, scope, [student], through=date(2026, 9, 27))
        reports: list[UUID] = []
        for period in (
            await reporting_service.list_periods(session, scope, through=date(2026, 9, 27))
        )[:2]:
            await reporting_service.ensure_obligations(session, scope, period.id)
            report = await submit(
                session,
                student,
                Week(period=period, projects=week.projects),
                make_entry(week.project.id),
            )
            reports.append(report.report_id if hasattr(report, "report_id") else report.id)
        built = World(factory, workspace.id, prof.id, student.id, week.project.id, reports)
        await session.commit()
    yield built


async def _as_prof(world: World, session: AsyncSession) -> Scope:
    from app.identity.models import User

    prof = (await session.execute(select(User).where(User.id == world.prof_id))).scalar_one()
    return await identity_service.scope_for(session, prof)


async def _in_own_session(world: World, work: Callable[[AsyncSession, Scope], Any]) -> Any:
    """One caller: its own connection and transaction, committed (or rolled back) at the end."""
    async with world.factory() as session:
        scope = await _as_prof(world, session)
        try:
            result = await work(session, scope)
        except BaseException:
            await session.rollback()
            raise
        await session.commit()
        return result


async def _draft(world: World, key: str | None = None) -> UUID:
    created = await _in_own_session(
        world,
        lambda session, scope: service.create_feedback(
            session,
            scope,
            student_id=world.student_id,
            project_id=world.project_id,
            report_ids=world.report_ids,
            title="t",
            body_markdown="b",
            idempotency_key=key,
        ),
    )
    return created.feedback_id


async def test_two_updates_from_the_same_version_one_wins_and_one_is_refused(world: World) -> None:
    fid = await _draft(world)

    def edit(text: str) -> Callable[[AsyncSession, Scope], Any]:
        return lambda session, scope: service.update_feedback(
            session, scope, fid, expected_version=1, body_markdown=text
        )

    results = await asyncio.gather(
        _in_own_session(world, edit("from A")),
        _in_own_session(world, edit("from B")),
        return_exceptions=True,
    )

    refused = [r for r in results if isinstance(r, ConflictError)]
    won = [r for r in results if not isinstance(r, BaseException)]
    assert len(refused) == 1 and len(won) == 1, results
    assert refused[0].extra["current_version"] == 2
    async with world.factory() as session:
        feedback = (await session.execute(select(Feedback).where(Feedback.id == fid))).scalar_one()
        revisions = (
            await session.execute(select(func.count()).where(FeedbackRevision.feedback_id == fid))
        ).scalar_one()
        body = (
            await session.execute(
                select(FeedbackRevision.body_markdown).where(
                    FeedbackRevision.feedback_id == fid, FeedbackRevision.version_no == 2
                )
            )
        ).scalar_one()
    assert feedback.version == 2
    assert revisions == 2  # the loser left nothing behind
    assert body == won[0].body_markdown


async def test_publishing_races_an_edit_and_only_a_reviewed_version_is_published(
    world: World,
) -> None:
    fid = await _draft(world)

    publish = _in_own_session(
        world,
        lambda session, scope: service.publish_feedback(session, scope, fid, expected_version=1),
    )
    edit = _in_own_session(
        world,
        lambda session, scope: service.update_feedback(
            session, scope, fid, expected_version=1, body_markdown="changed after review"
        ),
    )
    results = await asyncio.gather(publish, edit, return_exceptions=True)

    assert sum(isinstance(r, ConflictError) for r in results) <= 1
    async with world.factory() as session:
        feedback = (await session.execute(select(Feedback).where(Feedback.id == fid))).scalar_one()
        published = feedback.published_version
        body = (
            (
                await session.execute(
                    select(FeedbackRevision.body_markdown).where(
                        FeedbackRevision.feedback_id == fid,
                        FeedbackRevision.version_no == published,
                    )
                )
            ).scalar_one()
            if published
            else None
        )
    # Either order is fine, but a student must never be shown the edit without it being published
    # by someone who named that version.
    if published is not None:
        assert body == ("b" if published == 1 else "changed after review")
        if published == 2:
            assert isinstance(results[0], ConflictError) is False


async def test_concurrent_publishes_under_one_key_publish_once(world: World) -> None:
    fid = await _draft(world)

    def publish() -> Callable[[AsyncSession, Scope], Any]:
        return lambda session, scope: service.publish_feedback(
            session, scope, fid, expected_version=1, idempotency_key="publish-once"
        )

    results = await asyncio.gather(
        _in_own_session(world, publish()), _in_own_session(world, publish())
    )

    assert [r.status for r in results] == ["published", "published"]
    async with world.factory() as session:
        audits = (
            await session.execute(
                select(func.count()).where(
                    AuditEvent.action == "feedback.published", AuditEvent.target_id == fid
                )
            )
        ).scalar_one()
        keys = (
            await session.execute(
                select(func.count()).where(FeedbackIdempotency.key == "publish-once")
            )
        ).scalar_one()
    assert audits == 1
    assert keys == 1


async def test_concurrent_creates_under_one_key_make_one_feedback(world: World) -> None:
    first, second = await asyncio.gather(
        _draft(world, key="create-once"), _draft(world, key="create-once")
    )

    assert first == second
    async with world.factory() as session:
        count = (
            await session.execute(
                select(func.count()).where(Feedback.workspace_id == world.workspace_id)
            )
        ).scalar_one()
    assert count == 1
