"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload
The worker process lives in app.worker; both share app.core.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI

from app.ai import bootstrap as ai_bootstrap
from app.api.middleware import (
    RequestContextMiddleware,
    RequestIdFilter,
    SecurityHeadersMiddleware,
)
from app.api.problems import register_exception_handlers
from app.api.v1 import include_routers
from app.core import storage
from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, init_engine
from app.core.jobs import connector_for, procrastinate_app


def configure_logging(settings: Settings) -> None:
    fmt = (
        '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
        '"request_id":"%(request_id)s","message":"%(message)s"}'
        if settings.log_json
        else "%(asctime)s %(levelname)-5s [%(name)s] [%(request_id)s] %(message)s"
    )
    logging.basicConfig(level=settings.log_level, format=fmt, force=True)
    for handler in logging.getLogger().handlers:
        handler.addFilter(RequestIdFilter())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_engine(settings)
        # The provider is installed here rather than at import, so a test or a CLI command that
        # never starts the app never registers one (architecture §10).
        ai_bootstrap.install(settings)
        storage.register_store(storage.build_store(settings))
        # Without this every `defer_async` in the API process raises `AppNotOpen`, so a submitted
        # report would enqueue no assessment and a webhook would enqueue no sync (app.core.jobs).
        with ExitStack() as queue:
            queue.enter_context(procrastinate_app.replace_connector(connector_for(settings)))
            await procrastinate_app.open_async()
            try:
                yield
            finally:
                await procrastinate_app.close_async()
                await dispose_engine()

    application = FastAPI(
        title="Research Management System",
        version="0.1.0",
        docs_url="/api/docs" if settings.env != "prod" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    include_routers(application)
    return application


app = create_app()
