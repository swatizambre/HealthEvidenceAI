"""HTTP auth middleware for production-style OIDC / dev-JWT modes."""

from __future__ import annotations

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.oidc import validate_bearer_token
from app.auth.rbac import normalize_roles
from app.core.config import Settings
from app.core.exceptions import AppError

_PUBLIC_PREFIXES = (
    "/health",
    "/ready",
    "/metrics",
    "/api/v1/auth/dev-token",
    "/api/v1/auth/oidc/status",
    "/api/v1/auth/capabilities",
)

_DOCS_PREFIXES = (
    "/docs",
    "/openapi.json",
    "/redoc",
)

# Any of these (or their aliases) may sign into the local desk UI.
_PRODUCT_ROLES = frozenset(
    {"patient", "staff", "resident", "senior_clinician", "admin", "reviewer"}
)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        mode = self.settings.auth_mode.strip().lower()
        if mode in {"", "none", "off", "disabled"}:
            request.state.principal = None
            return await call_next(request)
        path = request.url.path
        # /auth/me is optional-auth: anonymous OK, bearer hydrated when present.
        if path == "/api/v1/auth/me" or path.startswith("/api/v1/auth/me/"):
            request.state.principal = None
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1].strip()
                try:
                    principal = validate_bearer_token(token, self.settings)
                    self._enforce_roles(principal, mode)
                    request.state.principal = principal
                except AppError:
                    request.state.principal = None
            return await call_next(request)
        if path == "/" or any(path == prefix or path.startswith(prefix + "/") for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)
        if path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)
        # Interactive docs only when Settings.docs_exposed() (local/test).
        if self.settings.docs_exposed() and any(
            path == prefix or path.startswith(prefix + "/") for prefix in _DOCS_PREFIXES
        ):
            return await call_next(request)
        # Meta catalog is public only on local/test desks — require auth in shared live.
        if (
            path.startswith("/api/v1/meta")
            and request.method == "GET"
            and self.settings.meta_public()
        ):
            return await call_next(request)
        # HIS/FHIR interface engine: shared API key (machine-to-machine).
        if path.startswith("/api/v1/hospital/pipeline"):
            interface_key = (self.settings.hospital_interface_api_key or "").strip()
            presented = (request.headers.get("x-hospital-api-key") or "").strip()
            if interface_key and presented and presented == interface_key:
                from app.auth.oidc import AuthPrincipal

                request.state.principal = AuthPrincipal(
                    subject="hospital-interface",
                    email="",
                    roles=("staff", "resident"),
                    raw_claims={"auth": "hospital_api_key"},
                )
                return await call_next(request)
        auth_header = request.headers.get("authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif path.startswith("/api/v1/events/stream"):
            # EventSource cannot set Authorization — accept access_token query.
            token = (request.query_params.get("access_token") or "").strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error_code": "OIDC_UNAUTHORIZED",
                    "message": "Bearer token required.",
                    "request_id": getattr(request.state, "request_id", ""),
                },
            )
        try:
            principal = validate_bearer_token(token, self.settings)
            self._enforce_roles(principal, mode)
            request.state.principal = principal
        except AppError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error_code": exc.error_code,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", ""),
                },
            )
        return await call_next(request)

    def _enforce_roles(self, principal: object, mode: str) -> None:
        roles = getattr(principal, "roles", ()) or ()
        have = set(normalize_roles(roles)) | {
            str(item).strip().lower() for item in roles if str(item).strip()
        }

        # Local desk: any product role is valid (UI mints staff/resident/senior/patient/admin).
        if mode == "dev-jwt":
            if have.intersection(_PRODUCT_ROLES) or normalize_roles(roles):
                return
            raise AppError(
                "OIDC_FORBIDDEN",
                "Signed-in role is not recognized for this workspace.",
                403,
            )

        configured = self.settings.oidc_required_roles.strip()
        if not configured:
            return
        allowed_raw = {part.strip() for part in configured.split(",") if part.strip()}
        allowed = set(normalize_roles(tuple(allowed_raw))) | {part.lower() for part in allowed_raw}
        # Legacy configs that only list "reviewer" still accept all product desk roles.
        if allowed <= {"reviewer", "senior_clinician"}:
            allowed |= set(_PRODUCT_ROLES)
        if allowed.intersection(have):
            return
        raise AppError(
            "OIDC_FORBIDDEN",
            "Signed-in role is not allowed for this environment.",
            403,
        )
