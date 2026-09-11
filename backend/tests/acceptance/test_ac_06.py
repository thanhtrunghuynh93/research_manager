"""AC-06 — Two students co-author a contribution, and one merges it | Joint attribution is
retained; merger status alone does not transfer authorship; project totals deduplicate the
artifact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.evidence import models, service
from app.evidence.connectors.base import Actor, CommitMeta, PullRequest
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from app.projects import service as projects_service

pytestmark = pytest.mark.acceptance

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


async def test_ac_06_joint_authorship_survives_the_merge(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
    week_for,
) -> None:
    week = await week_for(db, prof_scope, student_a)
    await projects_service.add_member(db, prof_scope, week.projects[0].id, student_id=student_b.id)

    connector = FakeRepositoryConnector(
        commits=[
            CommitMeta(
                sha="aaa",
                message="Add the loader",
                authored_at=WEEK,
                committed_at=WEEK,
                actors=[
                    Actor(role="author", login="student-a"),
                    Actor(role="author", email="b@example.edu"),
                ],
                paths=["src/loader.py"],
            )
        ],
        pull_requests=[
            PullRequest(
                number=7,
                title="Add the loader",
                state="merged",
                created_at=WEEK,
                updated_at=WEEK + timedelta(hours=1),
                merged_at=WEEK + timedelta(hours=1),
                merge_commit_sha="aaa",
                actors=[
                    Actor(role="author", login="student-a"),
                    Actor(role="merger", login="student-b"),
                ],
            )
        ],
    )
    repository = await service.connect_repository(
        db,
        prof_scope,
        provider="github",
        external_id="42",
        full_name="lab/baseline",
        connector=connector,
    )
    await service.link_project(db, prof_scope, repository.id, week.projects[0].id)
    await service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )
    identity_b = await service.map_identity(
        db, prof_scope, student_id=student_b.id, provider="github", email="b@example.edu"
    )
    await service.confirm_identity(db, prof_scope, identity_b.id)
    await service.map_identity(
        db, prof_scope, student_id=student_b.id, provider="github", login="student-b"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    commit_event = next(
        e
        for e in await service.list_events(db, prof_scope, repository.id)
        if e.kind is models.EventKind.COMMIT
    )
    on_commit = [
        c for c in await service.list_contributions(db, prof_scope) if c.event_id == commit_event.id
    ]
    # Joint attribution is retained for both authors.
    assert {c.student_id for c in on_commit} == {student_a.id, student_b.id}
    assert all(c.share is models.ContributionShare.JOINT for c in on_commit)

    # Merging is recorded as merging, not as authorship.
    merge_event = next(
        e
        for e in await service.list_events(db, prof_scope, repository.id)
        if e.kind is models.EventKind.PR_MERGED
    )
    on_merge = [
        c for c in await service.list_contributions(db, prof_scope) if c.event_id == merge_event.id
    ]
    merger = next(c for c in on_merge if c.student_id == student_b.id)
    assert merger.role is models.ContributionRole.MERGER
    assert merger.role is not models.ContributionRole.AUTHOR

    # The project counts the artifact once, not once per student.
    assert await service.distinct_event_count(db, prof_scope, project_id=week.projects[0].id) == 2
