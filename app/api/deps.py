"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import (
    ensure_care_team,
    ensure_patient_record_access,
    ensure_patient_write_target,
    filter_patient_list_for_principal,
)
from app.auth.rbac import ensure_any_role
from app.core.exceptions import AppError


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
        # Always commit the request transaction. Services flush mid-request; checking
        # session.dirty after flush would miss persisted inserts and roll them back.
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_principal(request: Request) -> AuthPrincipal | None:
    return getattr(request.state, "principal", None)


def _auth_disabled(request: Request) -> bool:
    settings = request.app.state.settings
    return settings.auth_mode.strip().lower() in {"", "none", "off", "disabled"}


def require_any_role(*roles: str) -> Callable[[Request], AuthPrincipal | None]:
    """Enforce product RBAC when AUTH_MODE is on; no-op in tests (AUTH_MODE=none)."""

    def _dependency(request: Request) -> AuthPrincipal | None:
        principal = get_principal(request)
        if _auth_disabled(request):
            return principal
        if principal is None:
            raise AppError("OIDC_UNAUTHORIZED", "Bearer token required.", 401)
        ensure_any_role(principal, *roles)
        return principal

    return _dependency


def require_care_team() -> Callable[[Request], AuthPrincipal | None]:
    """Staff / resident / senior / admin only — blocks patient role."""

    def _dependency(request: Request) -> AuthPrincipal | None:
        principal = get_principal(request)
        if _auth_disabled(request):
            return principal
        if principal is None:
            raise AppError("OIDC_UNAUTHORIZED", "Bearer token required.", 401)
        ensure_care_team(principal)
        return principal

    return _dependency


def enforce_patient_access(
    request: Request,
    patient_code: str,
    db: Session,
    *,
    action: str = "chart_access",
) -> AuthPrincipal | None:
    principal = get_principal(request)
    break_glass_id = request.headers.get("X-Break-Glass-Id") or request.headers.get(
        "x-break-glass-id"
    )
    ensure_patient_record_access(
        principal,
        patient_code,
        session=db,
        action=action,
        auth_disabled=_auth_disabled(request),
        break_glass_id=break_glass_id,
    )
    return principal


def enforce_patient_write(
    request: Request,
    patient_code: str | None,
    db: Session,
) -> str | None:
    principal = get_principal(request)
    return ensure_patient_write_target(
        principal,
        patient_code,
        session=db,
        auth_disabled=_auth_disabled(request),
    )


def patient_list_scope(request: Request) -> str | None:
    return filter_patient_list_for_principal(
        get_principal(request),
        auth_disabled=_auth_disabled(request),
    )
