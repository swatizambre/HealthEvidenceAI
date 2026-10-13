"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.a2a.handlers import register_default_handlers
from app.api.errors import register_exception_handlers
from app.api.middleware import AccessLogMiddleware
from app.api.routes import (
    a2a,
    ai,
    audit,
    auth,
    authorization,
    documents,
    events,
    evidence,
    graph,
    health,
    help,
    hospital,
    imaging,
    meta,
    opd,
    patients,
    policies,
    security,
    tools,
)
from app.auth.middleware import AuthMiddleware
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.safety import DISCLAIMER, PROTOTYPE_BANNER
from app.db.session import create_db_engine, create_session_factory, init_db, prepare_sqlite_path
from app.services.seed import seed_if_empty

DESCRIPTION = (
    "Prior-auth evidence prep and lifelong cross-facility health records: "
    "LangGraph agents, hybrid RAG, MCP tools, A2A messaging, MONAI-isolated imaging, "
    "OIDC authentication, and grounded LLM providers. "
    f"{PROTOTYPE_BANNER} {DISCLAIMER}"
)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.environment.strip().lower() not in {"test"}:
        settings.validate_live_configuration()
    prepare_sqlite_path(settings.database_url)
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    register_default_handlers()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.agents.checkpoints import close_checkpointer, setup_checkpointer
        from app.services.realtime import (
            get_hub,
            start_redis_subscriber,
            stop_redis_subscriber,
        )

        init_db(engine)
        try:
            setup_checkpointer(settings.database_url)
        except Exception:  # noqa: BLE001 — review still works via ReviewRun fallback
            pass
        if settings.seed_on_startup:
            session = session_factory()
            try:
                seed_if_empty(session)
            finally:
                session.close()
        try:
            get_hub().bind_loop(asyncio.get_running_loop())
        except RuntimeError:
            pass
        start_redis_subscriber()
        yield
        stop_redis_subscriber()
        close_checkpointer()
        engine.dispose()

    docs_on = settings.docs_exposed()
    app = FastAPI(
        title="HealthEvidence AI",
        version="0.3.0",
        description=DESCRIPTION,
        debug=False,
        lifespan=lifespan,
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(AuthMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origin_list(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    api_routers = (
        patients.router,
        policies.router,
        documents.router,
        evidence.router,
        graph.router,
        authorization.router,
        imaging.router,
        security.router,
        tools.router,
        a2a.router,
        auth.router,
        audit.router,
        events.router,
        hospital.router,
        ai.router,
        meta.router,
        opd.router,
        help.router,
    )
    for router in api_routers:
        app.include_router(router, prefix="/api/v1")

    @app.get("/", tags=["health"])
    def root() -> dict[str, str]:
        return {
            "name": "HealthEvidence AI",
            "docs": "/docs",
            "health": "/health",
            "disclaimer": PROTOTYPE_BANNER,
        }

    return app


app = create_app()
