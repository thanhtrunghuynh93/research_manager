"""API v1 router registry. Each module adds its router here as it lands."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.v1 import (
    admin,
    artifacts,
    assessments,
    assistant,
    auth,
    health,
    notifications,
    overview,
    projects,
    reports,
    repositories,
    tasks,
    users,
    workspaces,
)

API_PREFIX = "/api"
V1_PREFIX = "/api/v1"


def include_routers(app: FastAPI) -> None:
    app.include_router(health.router, prefix=API_PREFIX)

    v1 = APIRouter(prefix=V1_PREFIX)
    v1.include_router(auth.router)
    v1.include_router(users.router)
    v1.include_router(workspaces.router)
    v1.include_router(projects.router)
    v1.include_router(tasks.router)
    v1.include_router(reports.router)
    v1.include_router(artifacts.router)
    v1.include_router(repositories.router)
    v1.include_router(assessments.router)
    v1.include_router(overview.router)
    v1.include_router(notifications.router)
    v1.include_router(assistant.router)
    v1.include_router(admin.router)
    # ...
    app.include_router(v1)
