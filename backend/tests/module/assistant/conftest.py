"""A small workspace with a submitted week, shared by the assistant's service tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

AFTER_THE_WEEK = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)


@dataclass
class Workspace:
    period: Any
    project: Any
    student_scope: Scope


@pytest.fixture
def build_week(monkeypatch: pytest.MonkeyPatch):
    # Saving a calendar opens the weeks ahead of the reporting clock. Pinned inside the week of
    # 14 September with no horizon, that week is the only one open — the world these helpers
    # describe. Left to the wall clock, the week of the 21st opened too and became "this week".
    monkeypatch.setattr(
        "app.reporting.service.now", lambda: datetime(2026, 9, 15, 3, 0, tzinfo=UTC), raising=True
    )
    monkeypatch.setattr("app.reporting.service.DEFAULT_HORIZON", timedelta(0), raising=True)

    async def _build(
        db: AsyncSession,
        prof_scope: Scope,
        students: list[identity_models.User],
        *,
        title: str = "Retrieval baselines",
    ) -> Workspace:
        await reporting_service.configure_calendar(
            db,
            prof_scope,
            timezone="Asia/Ho_Chi_Minh",
            meeting_weekday=0,
            week_start_weekday=0,
            effective_from=date(2026, 9, 14),
        )
        project = await projects_service.create_project(
            db, prof_scope, title=title, stage="implementation"
        )
        await projects_service.update_project(db, prof_scope, project.id, status="active")
        for student in students:
            await projects_service.add_member(
                db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
            )
        periods = await reporting_service.ensure_periods(db, prof_scope, through=date(2026, 9, 20))
        await reporting_service.ensure_obligations(db, prof_scope, periods[0].id)
        return Workspace(
            period=periods[0],
            project=project,
            student_scope=await identity_service.scope_for(db, students[0]),
        )

    return _build


@pytest.fixture
def submit_entry():
    async def _submit(
        db: AsyncSession,
        student: identity_models.User,
        workspace: Workspace,
        **fields: str,
    ) -> Any:
        scope = await identity_service.scope_for(db, student)
        return await reporting_service.submit_report(
            db,
            scope,
            period_id=workspace.period.id,
            entries=[
                {
                    "project_id": workspace.project.id,
                    "stage": "implementation",
                    "work_performed": fields.get(
                        "work_performed", "Implemented the loader and ran the BM25 baseline."
                    ),
                    "results": fields.get(
                        "results", "nDCG@10 reached 0.412 on the internal split."
                    ),
                    "deviations": fields.get("deviations", ""),
                    "questions": fields.get("questions", ""),
                }
            ],
        )

    return _submit
