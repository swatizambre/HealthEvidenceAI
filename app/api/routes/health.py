"""Liveness and readiness endpoints."""



from fastapi import APIRouter, Request

from fastapi.responses import JSONResponse, PlainTextResponse

from sqlalchemy import text



from app.core.config import get_settings

from app.schemas.api import HealthResponse, ReadyResponse

from app.services.observability import prometheus_text



router = APIRouter(tags=["health"])





@router.get("/health", response_model=HealthResponse)

def health() -> HealthResponse:

    """Liveness — process is up (no dependency checks)."""

    return HealthResponse(status="ok")





@router.get("/metrics")

def metrics() -> PlainTextResponse:

    """Prometheus text exposition for packet/agent SLIs."""

    return PlainTextResponse(prometheus_text(), media_type="text/plain; version=0.0.4")





@router.get("/ready", response_model=ReadyResponse)

def ready(request: Request) -> ReadyResponse | JSONResponse:

    """Readiness — database + live-config surface for Kubernetes / load balancers."""

    settings = get_settings()

    practice = settings.hospital_practice_mode()

    base = {

        "environment": settings.env_name(),

        "auth_mode": settings.auth_mode.strip().lower(),

        "org_scope": settings.org_scope_enforced(),

        "hospital_mode": "synthetic_practice" if practice else "production_phi",

        "phi_live": not practice,

        "oidc_configured": bool(settings.oidc_issuer.strip() and settings.oidc_jwks_url.strip()),

        "seed_on_startup": bool(settings.seed_on_startup),

    }

    engine = getattr(request.app.state, "engine", None)

    if engine is None:

        return JSONResponse(

            status_code=503,

            content={

                "status": "not_ready",

                "database": "error",

                "detail": "Database engine is not initialized.",

                **base,

            },

        )

    try:

        with engine.connect() as connection:

            connection.execute(text("SELECT 1"))

        return ReadyResponse(status="ok", database="ok", detail="", **base)

    except Exception as exc:  # noqa: BLE001 — surface connectivity for ops

        return JSONResponse(

            status_code=503,

            content={

                "status": "not_ready",

                "database": "error",

                "detail": str(exc)[:200],

                **base,

            },

        )


