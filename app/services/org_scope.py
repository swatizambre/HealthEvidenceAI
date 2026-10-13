"""Organization / facility tenant scoping for care-team chart access."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLE_ADMIN, principal_roles
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models import Organization, Patient
from app.services.break_glass import require_valid_ticket


def resolve_org_id(session: Session, principal: AuthPrincipal) -> str | None:
    """Map token org_id or org_code to organizations.id."""
    if principal.org_id:
        row = session.get(Organization, principal.org_id)
        if row is not None and row.active:
            return row.id
    if principal.org_code:
        code = principal.org_code.strip().upper()
        row = session.scalar(select(Organization).where(Organization.org_code == code))
        if row is not None and row.active:
            return row.id
    return None


def org_scope_active(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return cfg.org_scope_enforced()


def ensure_org_patient_access(
    session: Session,
    principal: AuthPrincipal,
    patient: Patient,
    *,
    settings: Settings | None = None,
    break_glass_id: str | None = None,
) -> None:
    """When ENFORCE_ORG_SCOPE is on, care team may only open their org's patients.

    Admins may open another org's chart only with a valid, unexpired break-glass ticket.
    """
    if not org_scope_active(settings):
        return
    org_id = resolve_org_id(session, principal)
    patient_org = getattr(patient, "org_id", None)
    is_admin = ROLE_ADMIN in principal_roles(principal)

    if not patient_org:
        raise AppError(
            "ORG_SCOPE_FORBIDDEN",
            "This patient chart is not assigned to an organization.",
            403,
        )

    if org_id and patient_org == org_id:
        return

    # Same-org missing claim: non-admin still needs org binding.
    if not is_admin:
        if not org_id:
            raise AppError(
                "ORG_SCOPE_REQUIRED",
                "Care-team sign-in requires an organization binding (org_id or org_code claim).",
                403,
            )
        raise AppError(
            "ORG_SCOPE_FORBIDDEN",
            "This patient chart belongs to another organization.",
            403,
        )

    # Admin cross-org (or admin with no org claim viewing any assigned chart): break-glass.
    require_valid_ticket(
        break_glass_id,
        patient_id=patient.patient_code,
        actor=str(principal.subject or "")[:64],
    )


def care_team_org_filter_id(
    session: Session,
    principal: AuthPrincipal | None,
    *,
    settings: Settings | None = None,
) -> str | None:
    """Org UUID to filter patient lists, or None for unrestricted (auth off / flag off).

    Everyone (including admin) is tenant-filtered on list views when org scope is on.
    Cross-org chart opens still require break-glass on the individual chart path.
    """
    if principal is None or not org_scope_active(settings):
        return None
    org_id = resolve_org_id(session, principal)
    if not org_id:
        raise AppError(
            "ORG_SCOPE_REQUIRED",
            "Care-team sign-in requires an organization binding (org_id or org_code claim).",
            403,
        )
    return org_id
