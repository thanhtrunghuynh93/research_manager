"""Repository connections, developer identities, and evidence (REPO-01..05).

The evidence module was complete before these routes existed, which meant a professor could not
connect a repository without a Python shell. What the routes add is the authority question rather
than the behaviour: connecting a repository is workspace configuration and belongs to the
professor; claiming a developer identity is something a student does for themselves and for nobody
else (REPO-03).

The webhook is the exception to everything else in this API: no session, no Scope, and the HMAC is
the only credential. It is mounted here rather than in its own module so the signature check and
the connector that performs it stay side by side.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import ProfScopeDep, ScopeDep, SessionDep
from app.core.errors import (
    DependencyUnavailableError,
    ForbiddenError,
    UnauthenticatedError,
)
from app.core.jobs import defer_after_commit
from app.evidence import service
from app.evidence.schemas import (
    ContributionOut,
    EvidenceReferenceOut,
    IdentityOut,
    ProjectLinkOut,
    RepositoryOut,
    SyncRunOut,
)

router = APIRouter(tags=["evidence"])


class ConnectIn(BaseModel):
    provider: str = Field(default="github", pattern="^(github|gitlab)$")
    external_id: str = Field(min_length=1, max_length=200)
    full_name: str = Field(min_length=1, max_length=300)
    default_branch: str | None = None
    # The name of the installation the professor granted, never a token (requirements §9).
    credential_ref: str | None = None


class LinkProjectIn(BaseModel):
    project_id: UUID
    path_rules: list[str] = Field(default_factory=list)


class IdentityIn(BaseModel):
    provider: str = "github"
    login: str | None = None
    email: str | None = None
    # Only the professor may name someone else; a student omits it and gets themselves.
    student_id: UUID | None = None


class SyncStatusOut(BaseModel):
    repository_id: UUID
    full_name: str
    connection_state: str
    last_run: SyncRunOut | None = None


class EvidenceHitOut(BaseModel):
    evidence_ref_id: UUID
    text: str
    score: float
    source_kind: str
    source_id: UUID
    source_version: str
    locator: str
    project_id: UUID | None = None
    source_time: datetime


class WebhookAck(BaseModel):
    accepted: bool
    # False when nothing in this workspace matches the delivery. Not an error — but a webhook
    # landing nowhere looks identical to one working, and this is how you tell.
    matched: bool = False
    detail: str = ""


# ------------------------------------------------------------------ repositories (REPO-01)


@router.post(
    "/repositories",
    status_code=status.HTTP_201_CREATED,
    summary="Connect a repository the professor has granted read-only access to",
)
async def connect_repository(
    payload: ConnectIn, scope: ProfScopeDep, session: SessionDep
) -> RepositoryOut:
    """REPO-01: read-only, and the product stays fully usable without ever calling this."""
    from app.evidence.connectors import factory

    return await service.connect_repository(
        session,
        scope,
        provider=payload.provider,
        external_id=payload.external_id,
        full_name=payload.full_name,
        default_branch=payload.default_branch,
        credential_ref=payload.credential_ref,
        connector=factory.build(payload.provider, credential_ref=payload.credential_ref),
    )


@router.get("/repositories", summary="Connected repositories")
async def list_repositories(
    scope: ScopeDep, session: SessionDep, project_id: UUID | None = None
) -> list[RepositoryOut]:
    return await service.list_repositories(session, scope, project_id=project_id)


@router.post(
    "/repositories/{repository_id}/projects",
    status_code=status.HTTP_201_CREATED,
    summary="Say which project this repository's work belongs to",
)
async def link_project(
    repository_id: UUID, payload: LinkProjectIn, scope: ProfScopeDep, session: SessionDep
) -> ProjectLinkOut:
    """REPO-04: a repository serving several projects leaves unmatched paths unresolved rather
    than guessing, so the path rules are how attribution gets decided."""
    return await service.link_project(
        session,
        scope,
        repository_id,
        project_id=payload.project_id,
        path_rules=payload.path_rules,
    )


@router.get("/repositories/{repository_id}/projects", summary="Projects this repository serves")
async def list_project_links(
    repository_id: UUID, scope: ScopeDep, session: SessionDep
) -> list[ProjectLinkOut]:
    return await service.list_project_links(session, scope, repository_id)


@router.get("/repositories/{repository_id}/sync", summary="Last sync, its range, and any error")
async def sync_status(repository_id: UUID, scope: ScopeDep, session: SessionDep) -> SyncStatusOut:
    """REPO-05: never-synced is a state the screen shows, not an absence it hides."""
    repositories = await service.list_repositories(session, scope)
    repository = next((row for row in repositories if row.id == repository_id), None)
    if repository is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("repository not found")
    return SyncStatusOut(
        repository_id=repository.id,
        full_name=repository.full_name,
        connection_state=str(repository.connection_state),
        last_run=await service.sync_status(session, scope, repository_id),
    )


@router.post(
    "/repositories/{repository_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resync now",
)
async def sync_now(
    repository_id: UUID, scope: ProfScopeDep, session: SessionDep, full: bool = False
) -> SyncRunOut:
    """REPO-05: a manual resync is idempotent.

    Reprocessing the same range adds no event, no contribution and no score (AC-09).
    """
    from app.evidence.schemas import SyncKind

    if full:
        await service.reset_watermark(session, scope, repository_id)
    run = await service.sync_repository(
        session,
        scope,
        repository_id,
        connector=await service.connector_for(session, scope, repository_id),
        kind=SyncKind.MANUAL,
    )
    await service.resolve_contributions(session, repository_id)
    return run


# ------------------------------------------------------------------ identities (REPO-03)


@router.post(
    "/developer-identities",
    status_code=status.HTTP_201_CREATED,
    summary="Link a provider account to a student",
)
async def map_identity(payload: IdentityIn, scope: ScopeDep, session: SessionDep) -> IdentityOut:
    """A student may claim their own account; only the professor may map someone else's."""
    student_id = payload.student_id or scope.user_id
    if student_id != scope.user_id and not scope.is_prof:
        raise ForbiddenError("only the professor may map another student's account")
    return await service.map_identity(
        session,
        scope,
        student_id=student_id,
        provider=payload.provider,
        login=payload.login,
        email=payload.email,
    )


@router.get("/developer-identities", summary="Identities the caller may see")
async def list_identities(
    scope: ScopeDep, session: SessionDep, student_id: UUID | None = None
) -> list[IdentityOut]:
    return await service.list_identities(session, scope, student_id=student_id)


@router.post("/developer-identities/{identity_id}/confirm", summary="Confirm a claimed identity")
async def confirm_identity(
    identity_id: UUID, scope: ProfScopeDep, session: SessionDep
) -> IdentityOut:
    return await service.confirm_identity(session, scope, identity_id)


# ------------------------------------------------------------------ evidence reads


@router.get("/contributions", summary="Contributions attributed to the caller or a student")
async def list_contributions(
    scope: ScopeDep,
    session: SessionDep,
    student_id: UUID | None = None,
    project_id: UUID | None = None,
) -> list[ContributionOut]:
    """REPO-04: each student can see what was attributed to them, so misattribution can be
    challenged under ASSESS-08."""
    subject = student_id if scope.is_prof else scope.user_id
    return await service.list_contributions(
        session, scope, student_id=subject, project_id=project_id
    )


@router.get("/evidence/search", summary="Permission-filtered search over the evidence index")
async def search_evidence(
    scope: ScopeDep,
    session: SessionDep,
    q: Annotated[str, Field(min_length=1)],
    project_id: UUID | None = None,
    limit: int = 10,
) -> list[EvidenceHitOut]:
    """AUTH-02: the predicate sits inside each ranking arm, so a chunk outside the caller's scope
    is never scored and cannot surface through a snippet or a citation."""
    hits = await service.search_evidence(
        session, scope, query=q, project_id=project_id, limit=min(limit, 50)
    )
    return [
        EvidenceHitOut(
            evidence_ref_id=hit.evidence_ref_id,
            text=hit.text,
            score=hit.score,
            source_kind=str(hit.source_kind),
            source_id=hit.source_id,
            source_version=hit.source_version,
            locator=hit.locator,
            project_id=hit.project_id,
            source_time=hit.source_time,
        )
        for hit in hits
    ]


@router.get("/evidence/references/{reference_id}", summary="One citable evidence reference")
async def get_reference(
    reference_id: UUID, scope: ScopeDep, session: SessionDep
) -> EvidenceReferenceOut:
    return await service.get_reference(session, scope, reference_id)


# ------------------------------------------------------------------ webhooks (REPO-05, AC-09)


@router.post(
    "/webhooks/github",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Signed GitHub delivery",
    include_in_schema=False,
)
async def github_webhook(
    request: Request,
    session: SessionDep,
    response: Response,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    """No session and no Scope: the HMAC is the credential (architecture §8.1).

    A delivery whose signature does not hold is refused. One we cannot place — a repository this
    workspace never connected — is accepted and dropped, because asking GitHub to retry something
    that will never match is noise rather than resilience.
    """
    from app.evidence.connectors import factory

    verifier = factory.webhook_verifier("github")
    if verifier is None:
        # Configured app, no webhook secret: we cannot tell a real delivery from a forged one.
        raise DependencyUnavailableError("webhook verification is not configured")

    body = await request.body()
    headers = dict(request.headers)
    result = await service.ingest_webhook(session, headers=headers, body=body, connector=verifier)
    if result is None:
        raise UnauthenticatedError("the delivery signature did not verify")

    if result.accepted and result.repository_id is not None:
        # Architecture §8.3: a delivery triggers a targeted incremental run. Enqueued rather than
        # run here, so a slow provider call never holds the webhook response open and GitHub never
        # sees a timeout it would retry. Sent after the delivery row commits, so the job cannot
        # run against a transaction that never landed (app.core.jobs).
        from app.evidence import tasks

        defer_after_commit(
            session,
            tasks.sync_one,
            queueing_lock=f"sync:{result.repository_id}",
            repository_id=str(result.repository_id),
            kind="webhook",
        )

    return WebhookAck(
        accepted=result.accepted,
        matched=result.repository_id is not None,
        detail=result.detail or "",
    )
