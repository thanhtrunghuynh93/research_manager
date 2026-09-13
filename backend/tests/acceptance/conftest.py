"""Shared setup for the acceptance scenarios.

Each test file is named after the scenario in section 13 of the requirements and quotes its row,
so `grep AC-17` finds the specification, the architecture, the code, and the proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.identity import models as identity_models
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

TZ = "Asia/Ho_Chi_Minh"


@dataclass
class Workspace:
    period: Any
    projects: list[Any]
    student_scope: Scope


@pytest.fixture
async def week_for():
    """Build a configured week with a student enrolled on `project_count` active projects."""

    async def _build(
        db: AsyncSession,
        prof_scope: Scope,
        student: identity_models.User,
        *,
        project_count: int = 1,
        through: date = date(2026, 9, 20),
    ) -> Workspace:
        await reporting_service.configure_calendar(
            db,
            prof_scope,
            timezone=TZ,
            meeting_weekday=0,
            week_start_weekday=0,
            effective_from=date(2026, 9, 14),
        )
        projects = []
        for index in range(project_count):
            project = await projects_service.create_project(
                db, prof_scope, title=f"Project {index}", stage="implementation"
            )
            await projects_service.update_project(db, prof_scope, project.id, status="active")
            await projects_service.add_member(
                db, prof_scope, project.id, student_id=student.id, joined_on=date(2026, 9, 14)
            )
            projects.append(project)

        periods = await reporting_service.ensure_periods(db, prof_scope, through=through)
        await reporting_service.ensure_obligations(db, prof_scope, periods[0].id)
        return Workspace(
            period=periods[0],
            projects=projects,
            student_scope=await identity_service.scope_for(db, student),
        )

    return _build


def entry(project_id: UUID, work: str = "Implemented the data loader") -> dict[str, Any]:
    return {
        "project_id": project_id,
        "stage": "implementation",
        "work_performed": work,
        "results": "The loader reproduces the published split sizes.",
        "next_plan": {"items": [{"planned_outcome": "Run the baseline", "weight": 1}]},
    }
