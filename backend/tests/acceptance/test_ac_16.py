"""AC-16 — The application is restored from backup | Submitted versions, attachments, approvals,
permissions, and source references are recoverable within agreed recovery targets.

This is the one acceptance scenario that cannot be proved by reading the code, because what it
claims is about a process: that a dump taken on one night restores into a working system on
another. The requirement says to prove a restore before launch, and a plan to do that is not the
same thing as having done it.

So this test runs the real cycle — build a workspace, `pg_dump` it, `pg_restore` into an empty
database, and read it back — and asserts the things a professor would actually miss: the submitted
version and its text, the approval, the membership that decides who may see it, and the evidence
reference a citation resolves through. It also checks that the permission predicates still refuse
what they refused, because a restore that returns the data but loses the boundary is not a restore.

The Compose drill in `scripts/restore_drill.sh` remains the operational rehearsal: it measures the
wall-clock RTO on real infrastructure, which is the part this test deliberately does not claim.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.fake import FakeGateway
from app.assessment import service as assessment_service
from app.core.authz import Scope
from app.core.types import Role, Visibility
from app.evidence import service as evidence_service
from app.evidence.models import EvidenceSourceKind
from app.identity import service as identity_service
from app.identity.models import User
from app.projects import service as projects_service
from app.reporting import service as reporting_service
from tests.conftest import BACKEND_DIR

pytestmark = pytest.mark.acceptance

SOURCE_DB = "rm_ac16_source"
RESTORED_DB = "rm_ac16_restored"
DUMP_PATH = "/tmp/rm-ac16.dump"  # noqa: S108 - inside the database container, not this host

REPORTED_WORK = "Implemented the loader and reproduced the BM25 baseline."
SHARED_TEXT = "Project protocol: the evaluation split is frozen at the September snapshot."
PRIVATE_TEXT = "Professor only: discuss pacing before the review."
PASSWORD = "correct horse battery staple"  # noqa: S105 - fixture credential


@pytest.fixture
def container(postgres_container: Any) -> Any:
    if postgres_container is None:
        pytest.skip("the restore drill needs the database container's pg_dump and pg_restore")
    return postgres_container


def _run(container: Any, command_line: str) -> str:
    code, output = container.exec(["bash", "-lc", command_line])
    text = output.decode() if isinstance(output, bytes) else str(output)
    assert code == 0, f"{command_line} failed ({code}):\n{text}"
    return text


def _url(container: Any, database: str) -> str:
    base = container.get_connection_url()
    return base.rsplit("/", 1)[0] + f"/{database}"


async def _seed(url: str) -> dict[str, Any]:
    """A workspace with everything AC-16 names: a submitted version, an approval, a membership."""
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    previous = os.environ.get("RM_DATABASE_URL")
    os.environ["RM_DATABASE_URL"] = url
    try:
        # alembic's env.py opens its own event loop, so it runs on a thread rather than inside
        # the one this test is already using.
        await asyncio.to_thread(command.upgrade, cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("RM_DATABASE_URL", None)
        else:
            os.environ["RM_DATABASE_URL"] = previous

    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            bootstrapped = await identity_service.bootstrap_workspace(
                session,
                name="Restore drill lab",
                prof_email="prof@example.edu",
                prof_display_name="Professor",
            )
            await identity_service.accept_invitation(
                session, token=bootstrapped.token, password=PASSWORD
            )
            prof = await session.get(User, bootstrapped.user.id)
            assert prof is not None
            prof_scope = await identity_service.scope_for(session, prof)

            invited = await identity_service.invite_user(
                session, prof_scope, email="student-a@example.edu", role=Role.STUDENT
            )
            student_user = await identity_service.accept_invitation(
                session, token=invited.token, password=PASSWORD
            )
            student_id = student_user.id

            await reporting_service.configure_calendar(
                session,
                prof_scope,
                timezone="Asia/Ho_Chi_Minh",
                meeting_weekday=0,
                week_start_weekday=0,
                effective_from=date(2026, 9, 14),
            )
            project = await projects_service.create_project(
                session, prof_scope, title="Retrieval baselines", stage="implementation"
            )
            await projects_service.update_project(session, prof_scope, project.id, status="active")
            await projects_service.add_member(
                session, prof_scope, project.id, student_id=student_id, joined_on=date(2026, 9, 1)
            )
            period = (
                await reporting_service.ensure_periods(
                    session, prof_scope, through=date(2026, 9, 20)
                )
            )[0]
            await reporting_service.ensure_obligations(session, prof_scope, period.id)

            student = await session.get(User, student_id)
            assert student is not None
            student_scope = await identity_service.scope_for(session, student)
            version = await reporting_service.submit_report(
                session,
                student_scope,
                period_id=period.id,
                entries=[
                    {
                        "project_id": project.id,
                        "stage": "implementation",
                        "work_performed": REPORTED_WORK,
                        "results": "nDCG@10 reached 0.412.",
                    }
                ],
            )

            shared_source = uuid4()
            await evidence_service.index_evidence(
                session,
                workspace_id=prof_scope.workspace_id,
                source_kind=EvidenceSourceKind.ARTIFACT_VERSION,
                source_id=shared_source,
                source_version="1",
                text=SHARED_TEXT,
                visibility=Visibility.PROJECT_SHARED,
                locator="protocol.md",
                project_id=project.id,
            )
            private_source = uuid4()
            await evidence_service.index_evidence(
                session,
                workspace_id=prof_scope.workspace_id,
                source_kind=EvidenceSourceKind.ARTIFACT_VERSION,
                source_id=private_source,
                source_version="1",
                text=PRIVATE_TEXT,
                visibility=Visibility.PROFESSOR_ONLY,
                locator="pacing.md",
                project_id=project.id,
            )

            assessment = await assessment_service.run_pipeline(
                session,
                student_id=student_id,
                project_id=project.id,
                period_id=period.id,
                report_version_id=version.id,
                gateway=FakeGateway(),
            )
            assert assessment is not None
            await assessment_service.approve(session, prof_scope, assessment.id)
            await session.commit()

            return {
                "workspace_id": prof_scope.workspace_id,
                "prof_id": prof_scope.user_id,
                "student_id": student_id,
                "project_id": project.id,
                "period_id": period.id,
                "version_id": version.id,
                "assessment_id": assessment.id,
                "shared_source": shared_source,
                "private_source": private_source,
            }
    finally:
        await engine.dispose()


@pytest.fixture
async def restored(container: Any) -> Any:
    """Seed a database, dump it, restore into an empty one, and hand back a session factory."""
    source_url = _url(container, SOURCE_DB)
    restored_url = _url(container, RESTORED_DB)
    user = container.username

    for database in (SOURCE_DB, RESTORED_DB):
        _run(container, f"dropdb -U {user} --if-exists {database}")
        _run(container, f"createdb -U {user} {database}")

    seeded = await _seed(source_url)

    # Exactly the command the nightly backup runs, minus the age encryption around it.
    _run(container, f"pg_dump -U {user} -d {SOURCE_DB} -Fc -f {DUMP_PATH}")
    # And exactly the restore the runbook documents.
    _run(
        container,
        f"pg_restore -U {user} -d {RESTORED_DB} --clean --if-exists --no-owner "
        f"--no-privileges {DUMP_PATH}",
    )

    engine = create_async_engine(restored_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield seeded, factory
    finally:
        await engine.dispose()
        for database in (SOURCE_DB, RESTORED_DB):
            _run(container, f"dropdb -U {user} --if-exists {database}")


async def _evidence(session: Any, scope: Scope, source_id: Any) -> list[Any]:
    return await evidence_service.evidence_for_sources(
        session, scope, source_kind=EvidenceSourceKind.ARTIFACT_VERSION, source_ids=[source_id]
    )


async def test_ac_16_the_submitted_version_and_its_text_survive_the_restore(restored: Any) -> None:
    seeded, factory = restored
    async with factory() as session:
        prof = await _scope(session, seeded["prof_id"])
        version = await reporting_service.get_version(session, prof, seeded["version_id"])

        assert version.version_no == 1
        assert version.entries[0].work_performed == REPORTED_WORK
        assert version.submitted_at is not None


async def test_ac_16_the_approval_survives_and_the_student_can_still_read_it(
    restored: Any,
) -> None:
    """ASSESS-08: what was published stays published. A restore must not unpublish a week."""
    seeded, factory = restored
    async with factory() as session:
        student = await _scope(session, seeded["student_id"])
        visible = await assessment_service.list_assessments(
            session, student, student_id=seeded["student_id"]
        )

        assert [row.id for row in visible] == [seeded["assessment_id"]]
        assert visible[0].review_state == "approved"
        assert visible[0].published_at is not None


async def test_ac_16_the_evidence_reference_a_citation_resolves_through_survives(
    restored: Any,
) -> None:
    seeded, factory = restored
    async with factory() as session:
        prof = await _scope(session, seeded["prof_id"])
        hits = await _evidence(session, prof, seeded["shared_source"])

        assert [hit.text for hit in hits] == [SHARED_TEXT]
        assert hits[0].locator == "protocol.md"
        assert hits[0].source_version == "1"


async def test_ac_16_the_permission_boundary_is_restored_with_the_data(restored: Any) -> None:
    """A restore that returns the rows but loses the boundary is not a restore (AUTH-02)."""
    seeded, factory = restored
    async with factory() as session:
        student = await _scope(session, seeded["student_id"])

        # The membership came back, so the project's shared material is readable again.
        assert student.project_ids == frozenset({seeded["project_id"]})
        assert await _evidence(session, student, seeded["shared_source"])

        # And professor-only material is still refused to them, as it was before.
        assert await _evidence(session, student, seeded["private_source"]) == []
        prof = await _scope(session, seeded["prof_id"])
        assert await _evidence(session, prof, seeded["private_source"])


async def test_ac_16_the_immutability_guards_come_back_with_the_schema(restored: Any) -> None:
    """The triggers are part of the schema, so a dump that omitted them would restore a database
    where an approved history could be rewritten."""
    from sqlalchemy import text

    _seeded, factory = restored
    async with factory() as session:
        triggers = (
            await session.execute(
                text(
                    "SELECT event_object_table FROM information_schema.triggers "
                    "WHERE trigger_name LIKE 'trg_immutable%'"
                )
            )
        ).scalars()
        guarded = set(triggers)

    assert {"report_versions", "assessment_versions", "audit_events"} <= guarded


async def _scope(session: Any, user_id: Any) -> Scope:
    from app.identity.models import User

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    return await identity_service.scope_for(session, user)
