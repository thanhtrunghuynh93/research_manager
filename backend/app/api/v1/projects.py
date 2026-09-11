"""Project records, membership, and dated decisions (PROJ-01, PROJ-02, PROJ-06, UI-03)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.core.pagination import Page
from app.projects import service
from app.projects.schemas import (
    MembershipEndIn,
    MembershipIn,
    MembershipOut,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    ProjectProgressOut,
    ProjectStatus,
    ResearchDecisionIn,
    ResearchDecisionOut,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", summary="List the projects the caller may see")
async def list_projects(
    scope: ScopeDep,
    session: SessionDep,
    project_status: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: str | None = None,
) -> Page[ProjectOut]:
    return await service.list_projects(
        session, scope, status=project_status, limit=limit, cursor=cursor
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a project")
async def create_project(
    payload: ProjectIn, scope: ProfScopeDep, session: SessionDep
) -> ProjectOut:
    return await service.create_project(
        session,
        scope,
        title=payload.title,
        description=payload.description,
        stage=payload.stage,
        research_questions=payload.research_questions,
        intended_contributions=payload.intended_contributions,
        start_on=payload.start_on,
        target_on=payload.target_on,
        venue_target=payload.venue_target,
        shared_resources=payload.shared_resources,
    )


@router.get("/{project_id}", summary="Read one project")
async def get_project(project_id: UUID, scope: ScopeDep, session: SessionDep) -> ProjectOut:
    return await service.get_project(session, scope, project_id)


@router.patch("/{project_id}", summary="Update a project")
async def update_project(
    project_id: UUID, payload: ProjectPatch, scope: ProfScopeDep, session: SessionDep
) -> ProjectOut:
    return await service.update_project(
        session, scope, project_id, **payload.model_dump(exclude_unset=True)
    )


@router.get("/{project_id}/progress", summary="Milestone-weighted project progress")
async def project_progress(
    project_id: UUID, scope: ScopeDep, session: SessionDep
) -> ProjectProgressOut:
    return await service.project_progress(session, scope, project_id)


@router.get("/{project_id}/members", summary="List project members")
async def list_members(
    project_id: UUID,
    scope: ScopeDep,
    session: SessionDep,
    include_past: bool = False,
) -> list[MembershipOut]:
    return await service.list_members(session, scope, project_id, include_past=include_past)


@router.post(
    "/{project_id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Assign a student to the project",
)
async def add_member(
    project_id: UUID, payload: MembershipIn, scope: ProfScopeDep, session: SessionDep
) -> MembershipOut:
    return await service.add_member(
        session,
        scope,
        project_id,
        student_id=payload.student_id,
        responsibility=payload.responsibility,
        joined_on=payload.joined_on,
        planned_allocation=payload.planned_allocation,
    )


@router.post(
    "/{project_id}/members/{membership_id}/end",
    summary="End a membership, keeping its history",
)
async def end_membership(
    project_id: UUID,
    membership_id: UUID,
    payload: MembershipEndIn,
    scope: ProfScopeDep,
    session: SessionDep,
) -> MembershipOut:
    return await service.end_membership(session, scope, membership_id, left_on=payload.left_on)


@router.get("/{project_id}/decisions", summary="Dated research decisions")
async def list_decisions(
    project_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[ResearchDecisionOut]:
    return await service.list_decisions(session, scope, project_id)


@router.post(
    "/{project_id}/decisions",
    status_code=status.HTTP_201_CREATED,
    summary="Record a research decision and its rationale",
)
async def record_decision(
    project_id: UUID, payload: ResearchDecisionIn, scope: ProfScopeDep, session: SessionDep
) -> ResearchDecisionOut:
    return await service.record_decision(
        session,
        scope,
        project_id,
        decision=payload.decision,
        rationale=payload.rationale,
        decided_on=payload.decided_on,
        participant_ids=payload.participant_ids,
        related_evidence=payload.related_evidence,
    )
