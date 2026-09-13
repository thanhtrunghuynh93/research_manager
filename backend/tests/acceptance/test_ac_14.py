"""AC-14 — A student submits repetitive commits or verbose text without new substantive evidence |
Activity counts or length alone do not increase research-progress ratings.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fake import FakeGateway
from app.assessment import service
from app.core.authz import Scope
from app.evidence import service as evidence_service
from app.evidence.connectors.base import Actor, CommitMeta
from app.evidence.connectors.fake import FakeRepositoryConnector
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

pytestmark = pytest.mark.acceptance

WEEK = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)


async def _assess(
    db: AsyncSession,
    prof_scope: Scope,
    student: identity_models.User,
    *,
    work: str,
    commit_count: int,
) -> object:
    await reporting_service.configure_calendar(
        db,
        prof_scope,
        timezone="Asia/Ho_Chi_Minh",
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=date(2026, 9, 14),
    )
    project = await projects_service.create_project(
        db, prof_scope, title="Baseline", stage="implementation"
    )
    await projects_service.update_project(db, prof_scope, project.id, status="active")
    await projects_service.add_member(
        db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
    )
    period = (await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20)))[0]
    await reporting_service.ensure_obligations(db, prof_scope, period.id)

    if commit_count:
        connector = FakeRepositoryConnector(
            commits=[
                CommitMeta(
                    sha=f"sha{index}",
                    message="wip",
                    authored_at=WEEK,
                    committed_at=WEEK,
                    actors=[Actor(role="author", login="student-a")],
                    paths=["src/loader.py"],
                    additions=500,
                    deletions=400,
                    files_changed=1,
                )
                for index in range(commit_count)
            ]
        )
        repository = await evidence_service.connect_repository(
            db,
            prof_scope,
            provider="github",
            external_id="42",
            full_name="lab/baseline",
            connector=connector,
        )
        await evidence_service.link_project(db, prof_scope, repository.id, project.id)
        await evidence_service.map_identity(
            db, prof_scope, student_id=student.id, provider="github", login="student-a"
        )
        await evidence_service.sync_repository(db, prof_scope, repository.id, connector=connector)
        await evidence_service.resolve_contributions(db, repository.id)

    scope = await identity_service.scope_for(db, student)
    version = await reporting_service.submit_report(
        db,
        scope,
        period_id=period.id,
        entries=[
            {
                "project_id": project.id,
                "stage": "implementation",
                "work_performed": work,
                "results": "Work continues.",
                "next_plan": {},
            }
        ],
    )
    return await service.run_pipeline(
        db,
        student_id=student.id,
        project_id=project.id,
        period_id=period.id,
        report_version_id=version.id,
        gateway=FakeGateway(),
    )


async def test_ac_14_length_and_commit_volume_do_not_move_the_rating(
    db: AsyncSession,
    prof_scope: Scope,
    student_a: identity_models.User,
    student_b: identity_models.User,
) -> None:
    modest = await _assess(
        db,
        prof_scope,
        student_a,
        work="Fixed the loader's off-by-one on the last split.",
        commit_count=0,
    )
    voluminous = await _assess(
        db,
        prof_scope,
        student_b,
        work="Worked hard on the loader. " * 150,
        commit_count=40,
    )

    assert modest is not None and voluminous is not None
    assert voluminous.progress_index == modest.progress_index, (
        "forty commits and a thousand words did not buy a higher rating"
    )
