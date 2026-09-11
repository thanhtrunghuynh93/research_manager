"""REPO-03/REPO-04 and AC-06: who did what, and how sure we are.

Attribution is where this system can most easily be unfair, so the rules are narrow: a merger is
not an author, a co-author is a joint contributor rather than a second full one, an unrecognised
account stays unresolved rather than being guessed at, and a repository serving several projects
attributes nothing it cannot place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.errors import ForbiddenError
from app.evidence import models, service
from app.evidence.connectors.base import Actor, CommitMeta, PullRequest
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service

pytestmark = pytest.mark.module

WEEK = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def _commit(sha: str, actors: list[Actor], *, paths: list[str] | None = None) -> CommitMeta:
    return CommitMeta(
        sha=sha,
        message=f"Work on {sha}",
        authored_at=WEEK,
        committed_at=WEEK,
        actors=actors,
        paths=paths or ["src/loader.py"],
        additions=10,
        deletions=1,
        files_changed=1,
    )


async def _setup(
    db: AsyncSession, scope: Scope, connector: FakeRepositoryConnector, *, projects: int = 1
) -> tuple[list, object]:
    created = []
    for index in range(projects):
        project = await projects_service.create_project(
            db, scope, title=f"Project {index}", stage="implementation"
        )
        await projects_service.update_project(db, scope, project.id, status="active")
        created.append(project)
    repository = await service.connect_repository(
        db,
        scope,
        provider="github",
        external_id="42",
        full_name="lab/baseline",
        connector=connector,
    )
    return created, repository


async def test_a_verified_login_attributes_a_commit_to_its_author(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    connector = FakeRepositoryConnector(
        commits=[_commit("aaa", [Actor(role="author", login="student-a")])]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    await service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    contributions = await service.list_contributions(db, prof_scope, student_id=student_a.id)
    assert [c.role for c in contributions] == [models.ContributionRole.AUTHOR]
    assert contributions[0].share is models.ContributionShare.INDIVIDUAL
    assert contributions[0].attribution_state is models.AttributionState.RESOLVED
    assert contributions[0].project_id == projects[0].id


async def test_a_co_authored_commit_is_joint_and_counted_once_for_the_project(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # AC-06: joint attribution is retained; project totals deduplicate the artifact.
    connector = FakeRepositoryConnector(
        commits=[
            _commit(
                "aaa",
                [
                    Actor(role="author", login="student-a"),
                    Actor(role="author", login="student-b", email="b@example.edu"),
                ],
            )
        ]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    for student, login in ((student_a, "student-a"), (student_b, "student-b")):
        await service.map_identity(
            db, prof_scope, student_id=student.id, provider="github", login=login
        )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    everyone = await service.list_contributions(db, prof_scope)
    assert {c.student_id for c in everyone} == {student_a.id, student_b.id}
    assert all(c.share is models.ContributionShare.JOINT for c in everyone)
    assert len({c.event_id for c in everyone}) == 1, "one artifact, not two"
    assert await service.distinct_event_count(db, prof_scope, project_id=projects[0].id) == 1


async def test_merging_someone_elses_change_is_not_authorship(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # AC-06 / REPO-03: author, committer, reviewer, and merger are distinct roles.
    connector = FakeRepositoryConnector(
        pull_requests=[
            PullRequest(
                number=7,
                title="Add the loader",
                state="merged",
                created_at=WEEK,
                updated_at=WEEK + timedelta(hours=1),
                merged_at=WEEK + timedelta(hours=1),
                merge_commit_sha="ccc",
                actors=[
                    Actor(role="author", login="student-a"),
                    Actor(role="merger", login="student-b"),
                ],
            )
        ]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    for student, login in ((student_a, "student-a"), (student_b, "student-b")):
        await service.map_identity(
            db, prof_scope, student_id=student.id, provider="github", login=login
        )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    author = await service.list_contributions(db, prof_scope, student_id=student_a.id)
    merger = await service.list_contributions(db, prof_scope, student_id=student_b.id)
    assert [c.role for c in author] == [models.ContributionRole.AUTHOR]
    assert [c.role for c in merger] == [models.ContributionRole.MERGER]
    assert all(c.role is not models.ContributionRole.AUTHOR for c in merger)


async def test_a_review_is_recorded_as_a_review(
    db: AsyncSession, prof_scope: Scope, student_b: identity_models.User
) -> None:
    from app.evidence.connectors.base import Review

    connector = FakeRepositoryConnector(
        pull_requests=[
            PullRequest(
                number=7,
                title="Add the loader",
                state="merged",
                created_at=WEEK,
                updated_at=WEEK,
                merged_at=WEEK,
                merge_commit_sha="ccc",
                actors=[Actor(role="author", login="student-a")],
            )
        ]
    )
    connector.reviews[7] = [
        Review(
            external_id="r1",
            pull_request_number=7,
            state="approved",
            submitted_at=WEEK,
            actor=Actor(role="reviewer", login="student-b"),
        )
    ]
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    await service.map_identity(
        db, prof_scope, student_id=student_b.id, provider="github", login="student-b"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    contributions = await service.list_contributions(db, prof_scope, student_id=student_b.id)
    assert [c.role for c in contributions] == [models.ContributionRole.REVIEWER]


async def test_an_unrecognised_account_stays_unresolved(
    db: AsyncSession, prof_scope: Scope
) -> None:
    # REPO-03: record ambiguous identities rather than guessing whose work it is.
    connector = FakeRepositoryConnector(
        commits=[_commit("aaa", [Actor(role="author", login="nobody-we-know")])]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    assert await service.list_contributions(db, prof_scope) == []
    unresolved = await service.unresolved_actors(db, prof_scope, repository.id)
    assert "nobody-we-know" in unresolved


async def test_a_bot_is_labelled_and_attributed_to_nobody(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REPO-07: exclude or label bot activity when interpreting contributions.
    connector = FakeRepositoryConnector(
        commits=[
            _commit("aaa", [Actor(role="author", login="dependabot[bot]", is_bot=True)]),
            _commit("bbb", [Actor(role="author", login="student-a")]),
        ]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    await service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    contributions = await service.list_contributions(db, prof_scope)
    assert len(contributions) == 1
    assert contributions[0].student_id == student_a.id


async def test_a_repository_serving_two_projects_uses_path_rules(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REPO-04: use an approved path mapping, or mark project attribution unresolved.
    connector = FakeRepositoryConnector(
        commits=[
            _commit("aaa", [Actor(role="author", login="student-a")], paths=["baseline/train.py"]),
            _commit("bbb", [Actor(role="author", login="student-a")], paths=["theory/proof.tex"]),
            _commit("ccc", [Actor(role="author", login="student-a")], paths=["README.md"]),
        ]
    )
    projects, repository = await _setup(db, prof_scope, connector, projects=2)
    await service.link_project(
        db, prof_scope, repository.id, projects[0].id, path_rules=["baseline/**"]
    )
    await service.link_project(
        db, prof_scope, repository.id, projects[1].id, path_rules=["theory/**"]
    )
    await service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    contributions = await service.list_contributions(db, prof_scope, student_id=student_a.id)
    by_state = {c.attribution_state for c in contributions}
    assert models.AttributionState.UNRESOLVED_PROJECT in by_state, "README matches no rule"
    resolved = [c for c in contributions if c.attribution_state is models.AttributionState.RESOLVED]
    assert {c.project_id for c in resolved} == {projects[0].id, projects[1].id}


async def test_a_single_project_repository_needs_no_path_rules(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    connector = FakeRepositoryConnector(
        commits=[_commit("aaa", [Actor(role="author", login="student-a")], paths=["anywhere.py"])]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    await service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)

    contributions = await service.list_contributions(db, prof_scope)
    assert contributions[0].attribution_state is models.AttributionState.RESOLVED
    assert contributions[0].project_id == projects[0].id


async def test_resolving_twice_changes_nothing(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # AC-09: reprocessing must not increase anyone's contributions.
    connector = FakeRepositoryConnector(
        commits=[_commit("aaa", [Actor(role="author", login="student-a")])]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    await service.map_identity(
        db, prof_scope, student_id=student_a.id, provider="github", login="student-a"
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)
    await service.resolve_contributions(db, repository.id)

    assert len(await service.list_contributions(db, prof_scope)) == 1


async def test_an_email_alias_needs_confirmation_before_it_attributes(
    db: AsyncSession, prof_scope: Scope, student_a: identity_models.User
) -> None:
    # REPO-03: explicitly confirmed email aliases, not inferred ones.
    connector = FakeRepositoryConnector(
        commits=[_commit("aaa", [Actor(role="author", email="alias@personal.example")])]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    pending = await service.map_identity(
        db,
        prof_scope,
        student_id=student_a.id,
        provider="github",
        email="alias@personal.example",
        verification=models.IdentityVerification.PENDING,
    )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)

    await service.resolve_contributions(db, repository.id)
    assert await service.list_contributions(db, prof_scope) == []

    await service.confirm_identity(db, prof_scope, pending.id)
    await service.resolve_contributions(db, repository.id)

    assert len(await service.list_contributions(db, prof_scope)) == 1


async def test_a_student_sees_the_contributions_attributed_to_them(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    # REPO-04: each student can view what is attributed to them, so it can be challenged.
    connector = FakeRepositoryConnector(
        commits=[
            _commit("aaa", [Actor(role="author", login="student-a")]),
            _commit("bbb", [Actor(role="author", login="student-b")]),
        ]
    )
    projects, repository = await _setup(db, prof_scope, connector)
    await service.link_project(db, prof_scope, repository.id, projects[0].id)
    for student, login in ((student_a, "student-a"), (student_b, "student-b")):
        await projects_service.add_member(db, prof_scope, projects[0].id, student_id=student.id)
        await service.map_identity(
            db, prof_scope, student_id=student.id, provider="github", login=login
        )
    await service.sync_repository(db, prof_scope, repository.id, connector=connector)
    await service.resolve_contributions(db, repository.id)

    scope = await identity_service.scope_for(db, student_a)
    mine = await service.list_contributions(db, scope)

    assert [c.student_id for c in mine] == [student_a.id]
    events = await service.list_events(db, scope, repository.id)
    assert [e.source_version for e in events] == ["aaa"], "only my own attributed events"


async def test_only_the_professor_maps_an_identity_for_someone_else(
    db: AsyncSession, student_a_scope: Scope, student_b: identity_models.User
) -> None:
    with pytest.raises(ForbiddenError):
        await service.map_identity(
            db, student_a_scope, student_id=student_b.id, provider="github", login="student-b"
        )
