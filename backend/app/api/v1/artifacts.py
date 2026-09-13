"""Attachments (REP-04).

No file body passes through this process in either direction. An upload gets a presigned PUT after
the size check; a download gets a presigned GET after the permission check. The application keeps
the authority over what counts as evidence and hands the bytes to the object store.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.deps import ScopeDep, SessionDep
from app.reporting import artifacts as service
from app.reporting.schemas import ExtractionState

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class UploadRequest(BaseModel):
    project_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)
    # The client hashes the file before asking. It is what the server verifies against afterwards.
    sha256: str = Field(min_length=64, max_length=64)
    supported_claim: str = ""
    entry_id: UUID | None = None
    period_id: UUID | None = None
    # Set to replace an existing artifact, keeping its identity and its earlier versions.
    artifact_id: UUID | None = None


class UploadGrantOut(BaseModel):
    artifact_id: UUID
    version_no: int
    url: str
    expires_in: int
    headers: dict[str, str]


class LinkRequest(BaseModel):
    project_id: UUID
    url: str = Field(min_length=1, max_length=2000)
    supported_claim: str = ""
    entry_id: UUID | None = None
    period_id: UUID | None = None


class ArtifactOut(BaseModel):
    artifact_id: UUID
    owner_student_id: UUID
    project_id: UUID | None = None
    period_id: UUID | None = None
    entry_id: UUID | None = None
    kind: str
    filename: str
    supported_claim: str = ""
    source_url: str | None = None
    version_no: int
    byte_size: int
    content_type: str
    extraction_state: ExtractionState
    extraction_note: str = ""
    uploaded: bool
    created_at: datetime


class ArtifactVersionOut(BaseModel):
    artifact_id: UUID
    version_id: UUID
    version_no: int
    filename: str
    sha256: str | None = None
    byte_size: int
    content_type: str
    extraction_state: ExtractionState
    # Why text is missing or partial, in words the coverage note can carry (ASSESS-06).
    extraction_note: str
    truncated: bool
    uploaded: bool
    created_at: datetime


class DownloadOut(BaseModel):
    url: str
    expires_in: int


@router.get("", summary="The attachments the caller may see")
async def list_artifacts(
    scope: ScopeDep,
    session: SessionDep,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
    period_id: UUID | None = None,
) -> list[ArtifactOut]:
    """AC-02: a professor sees the workspace's attachments, a student only their own.

    Without this there is no way back to a file. The upload response was the only place an
    artifact id ever appeared, so a reloaded page lost its own attachments and the professor
    could not reach a student's at all.
    """
    rows = await service.list_artifacts(
        session, scope, student_id=student_id, project_id=project_id, period_id=period_id
    )
    return [ArtifactOut(**{**asdict(row), "kind": row.kind.value}) for row in rows]


@router.post(
    "/uploads", status_code=status.HTTP_201_CREATED, summary="Ask permission to upload one file"
)
async def request_upload(
    payload: UploadRequest, scope: ScopeDep, session: SessionDep
) -> UploadGrantOut:
    """The size limit is enforced here, before a byte crosses the network (REP-04)."""
    grant = await service.request_upload(
        session,
        scope,
        project_id=payload.project_id,
        filename=payload.filename,
        byte_size=payload.byte_size,
        sha256=payload.sha256,
        supported_claim=payload.supported_claim,
        entry_id=payload.entry_id,
        period_id=payload.period_id,
        artifact_id=payload.artifact_id,
    )
    return UploadGrantOut(
        artifact_id=grant.artifact_id,
        version_no=grant.version_no,
        url=grant.url,
        expires_in=grant.expires_in,
        headers=grant.headers,
    )


@router.post("/{artifact_id}/confirm", summary="Confirm the bytes arrived, and extract them")
async def confirm_upload(
    artifact_id: UUID, scope: ScopeDep, session: SessionDep
) -> ArtifactVersionOut:
    """Nothing is attached until the object exists and its checksum matches what was declared."""
    version = await service.confirm_upload(session, scope, artifact_id)
    return ArtifactVersionOut(**_as(version))


@router.post("/links", status_code=status.HTTP_201_CREATED, summary="Attach a link")
async def attach_link(
    payload: LinkRequest, scope: ScopeDep, session: SessionDep
) -> ArtifactVersionOut:
    """A refused link is still recorded, with the reason it was not followed (REP-04)."""
    version = await service.attach_link(
        session,
        scope,
        project_id=payload.project_id,
        url=payload.url,
        supported_claim=payload.supported_claim,
        entry_id=payload.entry_id,
        period_id=payload.period_id,
    )
    return ArtifactVersionOut(**_as(version))


@router.get("/{artifact_id}/versions", summary="Every stored version of one artifact")
async def list_versions(
    artifact_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[ArtifactVersionOut]:
    return [
        ArtifactVersionOut(**_as(version))
        for version in await service.list_versions(session, scope, artifact_id)
    ]


@router.get("/{artifact_id}/download", summary="A time-limited link to the file")
async def download(
    artifact_id: UUID,
    scope: ScopeDep,
    session: SessionDep,
    version_no: int | None = None,
) -> DownloadOut:
    """AC-02: issued only after the same predicate that governs reading the record."""
    presigned = await service.download_url(session, scope, artifact_id, version_no=version_no)
    return DownloadOut(url=presigned.url, expires_in=presigned.expires_in)


def _as(version: service.ArtifactVersionOut) -> dict[str, Any]:
    fields: dict[str, Any] = asdict(version)
    fields.pop("storage_key", None)  # a bucket path is not the client's business
    return fields
