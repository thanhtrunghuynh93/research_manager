"""Async row builders shared across the test suite.

Plain functions rather than factory_boy classes: the ORM is async, and a test reads better when the
row it depends on is built by one awaited call with explicit fields.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import Scope
from app.core.types import Role
from app.identity import models, security
from app.identity import service as identity_service
from app.projects import service as projects_service
from app.reporting import service as reporting_service

_counter = itertools.count(1)

DEFAULT_PASSWORD = "correct horse battery staple"  # noqa: S105 - fixture credential


async def make_workspace(
    session: AsyncSession,
    *,
    name: str = "Research Lab",
    timezone: str = "Asia/Ho_Chi_Minh",
) -> models.Workspace:
    workspace = models.Workspace(name=name, timezone=timezone)
    session.add(workspace)
    await session.flush()
    return workspace


async def make_user(
    session: AsyncSession,
    workspace: models.Workspace,
    *,
    role: Role = Role.STUDENT,
    email: str | None = None,
    display_name: str | None = None,
    state: models.UserState = models.UserState.ACTIVE,
    password: str | None = DEFAULT_PASSWORD,
) -> models.User:
    address = security.normalize_email(email or f"user{next(_counter)}@example.edu")
    user = models.User(
        workspace_id=workspace.id,
        role=role,
        email=address,
        display_name=display_name or address.split("@")[0],
        password_hash=security.hash_password(password) if password else None,
        state=state,
    )
    session.add(user)
    await session.flush()
    # Belonging is a membership row, not the column (ADR 0015). The service writes one whenever it
    # creates an account; a factory that skipped it would build users nobody is on the roll of.
    session.add(models.WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await session.flush()
    return user


# --------------------------------------------------------------------- projects and weeks

TZ = "Asia/Ho_Chi_Minh"
WEEK_START = date(2026, 9, 14)
WEEK_END = date(2026, 9, 20)


async def make_project(
    session: AsyncSession,
    scope: Scope,
    *,
    title: str = "Baseline evaluation",
    stage: str = "implementation",
    active: bool = True,
    **fields: Any,
) -> Any:
    """A project, activated unless told otherwise, so members can be added and weeks owed."""
    project = await projects_service.create_project(
        session, scope, title=title, stage=stage, **fields
    )
    if active:
        await projects_service.update_project(session, scope, project.id, status="active")
    return project


@dataclass
class Week:
    """One configured reporting week: its period, the projects it covers, and the memberships."""

    period: Any
    projects: list[Any]
    memberships: list[Any] = field(default_factory=list)

    @property
    def project(self) -> Any:
        return self.projects[0]


async def make_week(
    session: AsyncSession,
    prof_scope: Scope,
    students: list[models.User],
    *,
    projects: int = 1,
    title: str | None = None,
    joined_on: date = WEEK_START,
    grace_minutes: int = 0,
    through: date = WEEK_END,
) -> Week:
    """The week of 14 September in a Monday-meeting calendar, with every student on every project.

    Project titles are `title`, or "Project 0", "Project 1", ... Obligations are derived for the
    first period, so the week is ready to be submitted against.
    """
    await reporting_service.configure_calendar(
        session,
        prof_scope,
        timezone=TZ,
        meeting_weekday=0,
        week_start_weekday=0,
        effective_from=WEEK_START,
        grace_minutes=grace_minutes,
    )
    built: list[Any] = []
    memberships: list[Any] = []
    for index in range(projects):
        project = await make_project(
            session, prof_scope, title=title if title is not None else f"Project {index}"
        )
        for student in students:
            memberships.append(
                await projects_service.add_member(
                    session, prof_scope, project.id, student_id=student.id, joined_on=joined_on
                )
            )
        built.append(project)
    period = (await reporting_service.ensure_periods(session, prof_scope, through=through))[0]
    await reporting_service.ensure_obligations(session, prof_scope, period.id)
    return Week(period=period, projects=built, memberships=memberships)


def make_entry(
    project_id: Any, *, work: str = "Implemented the data loader", **fields: Any
) -> dict:
    """One report entry with something written in it; override any field by keyword."""
    return {
        "project_id": project_id,
        "stage": "implementation",
        "work_performed": work,
        "results": "The loader reproduces the published split sizes.",
        "next_plan": {"items": [{"planned_outcome": "Run the baseline end to end"}]},
        **fields,
    }


async def submit(
    session: AsyncSession, student: models.User, week: Week, *entries: dict, **kwargs: Any
) -> Any:
    """Submit `entries` (by default one per project in the week) as `student`."""
    scope = await identity_service.scope_for(session, student)
    return await reporting_service.submit_report(
        session,
        scope,
        period_id=week.period.id,
        entries=list(entries) or [make_entry(project.id) for project in week.projects],
        **kwargs,
    )


# --------------------------------------------------------------------- http


async def login(client: AsyncClient, user: models.User, password: str = DEFAULT_PASSWORD) -> None:
    """Sign `user` in on `client`; the session cookie rides on every later request."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    assert response.status_code == 200, response.text
