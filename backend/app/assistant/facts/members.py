"""Facts about who is on what, and when they were (PROJ-02, AUTH-03).

`left_on` is exclusive, so "who is on this project" is a question about an instant, not a flag.
Answering it from the current row would tell the professor that a student removed this morning is
still a member.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.facts.base import Citation, Fact, FactQuery, fact
from app.identity import service as identity_service
from app.projects import service as projects_service


@fact("members")
async def members(session: AsyncSession, query: FactQuery) -> Fact | None:
    if query.project_id is None:
        return None

    project = await projects_service.get_project(session, query.scope, query.project_id)
    on_date = query.as_of.date()
    rows = []
    # Past memberships are included and then filtered by date: a membership that has ended was
    # still in force earlier, and PROJ-02 keeps that history precisely so it can be answered.
    memberships = await projects_service.list_members(
        session, query.scope, query.project_id, include_past=True
    )
    for membership in memberships:
        if membership.joined_on > on_date:
            continue
        if membership.left_on is not None and membership.left_on <= on_date:
            continue  # left_on is exclusive: the first day they are no longer a member
        student = await identity_service.get_user(session, query.scope, membership.student_id)
        rows.append(
            {
                "student_id": str(membership.student_id),
                "display_name": student.display_name,
                "responsibility": membership.responsibility,
                "joined_on": membership.joined_on.isoformat(),
            }
        )

    return Fact(
        name="members",
        label=f"Members of {project.title}",
        value=len(rows),
        as_of=query.as_of,
        rows=rows,
        citations=[
            Citation(
                source_kind="project",
                source_id=project.id,
                locator=f"/projects/{project.id}",
                label=project.title,
            )
        ],
        note=(
            "Membership is evaluated at the as-of date; a departure dated that day already applies."
        ),
    )


@fact("projects_for_student")
async def projects_for_student(session: AsyncSession, query: FactQuery) -> Fact | None:
    student_id = query.student_id or (None if query.scope.is_prof else query.scope.user_id)
    if student_id is None:
        return None

    student = await identity_service.get_user(session, query.scope, student_id)
    project_ids = await projects_service.student_project_ids(
        session, query.scope.workspace_id, student_id
    )
    rows = []
    citations = []
    for project_id in sorted(project_ids, key=str):
        project = await projects_service.get_project(session, query.scope, project_id)
        rows.append(
            {
                "project_id": str(project.id),
                "title": project.title,
                "stage": str(project.stage),
                "status": str(project.status),
            }
        )
        citations.append(
            Citation(
                source_kind="project",
                source_id=project.id,
                locator=f"/projects/{project.id}",
                label=project.title,
            )
        )

    return Fact(
        name="projects_for_student",
        label=f"Projects {student.display_name} is currently on",
        value=len(rows),
        as_of=query.as_of,
        rows=rows,
        citations=citations,
    )
