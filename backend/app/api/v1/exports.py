"""Authorized exports (UI-06).

There is no separate export permission. The bundle is assembled from the same service calls the
screens use, so a download carries exactly the authority of the account that asked for it (AC-02).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import ScopeDep, SessionDep
from app.exports import service
from app.exports.schemas import BundleOut

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/kinds", summary="What this account may export")
async def list_kinds(scope: ScopeDep) -> dict[str, list[str]]:
    available = [
        kind for kind in service.KINDS if scope.is_prof or kind not in service.PROFESSOR_ONLY
    ]
    return {"kinds": available, "default": list(service.DEFAULT_KINDS)}


@router.get("", summary="A machine-readable bundle of authorized records")
async def build_bundle(
    scope: ScopeDep,
    session: SessionDep,
    kinds: Annotated[list[str] | None, Query()] = None,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> BundleOut:
    """Identifiers, versions, relationships, and approval status (requirements §11)."""
    bundle = await service.build(
        session,
        scope,
        kinds=kinds,
        student_id=student_id,
        project_id=project_id,
        since=since,
        until=until,
    )
    return BundleOut(**bundle.as_dict())


@router.get("/{kind}.csv", summary="One kind as a spreadsheet", response_class=Response)
async def build_csv(
    kind: str,
    scope: ScopeDep,
    session: SessionDep,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    bundle = await service.build(
        session,
        scope,
        kinds=[kind],
        student_id=student_id,
        project_id=project_id,
        since=since,
        until=until,
    )
    return Response(
        content=service.to_csv(bundle, kind),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )
