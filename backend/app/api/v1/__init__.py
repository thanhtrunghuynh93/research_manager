"""API v1 router registry. Each module adds its router here as it lands."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.v1 import (
    assessments,
    auth,
    health,
    milestones,
    notifications,
    projects,
    reports,
    users,
)

API_PREFIX = "/api"
V1_PREFIX = "/api/v1"


def include_routers(app: FastAPI) -> None:
    app.include_router(health.router, prefix=API_PREFIX)

    v1 = APIRouter(prefix=V1_PREFIX)
    v1.include_router(auth.router)
    v1.include_router(users.router)
    v1.include_router(projects.router)
    v1.include_router(milestones.router)
    v1.include_router(reports.router)
    v1.include_router(assessments.router)
    v1.include_router(notifications.router)
    # ...
    app.include_router(v1)
