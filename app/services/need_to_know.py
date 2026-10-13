"""Incremental need-to-know: assigned cases are not open to every org colleague."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLE_ADMIN, ROLE_SENIOR, principal_roles
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models import AuthorizationCase


def need_to_know_active(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return cfg.need_to_know_enforced()


def ensure_case_need_to_know(
    session: Session,
    principal: AuthPrincipal | None,
    case: AuthorizationCase,
    *,
    settings: Settings | None = None,
) -> None:
    """When enabled, only assignee / senior / admin may act on an assigned case."""
    if principal is None or not need_to_know_active(settings):
        return
    assignee = str(getattr(case, "assigned_to", None) or "").strip()
    if not assignee:
        return
    roles = principal_roles(principal)
    if ROLE_ADMIN in roles or ROLE_SENIOR in roles:
        return
    subject = str(getattr(principal, "subject", "") or "").strip()
    if subject and subject == assignee:
        return
    raise AppError(
        "NEED_TO_KNOW_FORBIDDEN",
        "This case is assigned to another clinician. Ask an admin to reassign, "
        "or sign in as the assignee / senior clinician.",
        403,
    )
