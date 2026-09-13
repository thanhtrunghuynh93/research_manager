"""Facts about the freshness of the evidence itself (REPO-05, AC-04, ASSESS-06).

A repository that has not synced is a gap in what we can see, and saying so is the whole point. The
failure this guards against is reporting quiet evidence as quiet work.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.facts.base import Citation, Fact, FactQuery, fact
from app.evidence import service as evidence_service

STALE_AFTER = timedelta(hours=48)


@fact("stale_repositories")
async def stale_repositories(session: AsyncSession, query: FactQuery) -> Fact:
    repositories = await evidence_service.list_repositories(
        session, query.scope, project_id=query.project_id
    )
    rows = []
    stale_repos = []
    for repository in repositories:
        run = await evidence_service.sync_status(session, query.scope, repository.id)
        finished = run.finished_at if run is not None else None
        state = str(run.state) if run is not None else "never run"
        stale = finished is None or (query.as_of - finished) > STALE_AFTER
        if not stale and state == "completed":
            continue
        stale_repos.append(repository)
        rows.append(
            {
                "repository_id": str(repository.id),
                "full_name": repository.full_name,
                "state": state,
                "last_finished_at": None if finished is None else finished.isoformat(),
                "error_summary": (run.error_summary if run is not None else None),
            }
        )

    return Fact(
        name="stale_repositories",
        label="Repositories with stale or failed synchronisation",
        value=len(rows),
        as_of=query.as_of,
        rows=rows,
        citations=[
            Citation(
                source_kind="repository",
                source_id=repository.id,
                locator=f"/projects?repository={repository.id}",
                label=repository.full_name,
            )
            # The stale ones, not every one: citing twenty healthy repositories as the support
            # for "one repository is stale" is worse than citing nothing (QA-03).
            for repository in stale_repos
        ],
        note=(
            "A repository that has not synced recently means the evidence is incomplete, not that "
            "no work was done."
        ),
    )
