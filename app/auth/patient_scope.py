"""Patient record isolation — one patient must never read another patient's data.

Legal/practical stance (demo + production path):
- Patients: right of access to *their own* record only (self-scope via JWT patient_id).
- Care team (staff/resident/senior/admin): need-to-know chart access for PA / clinical desk.
  Production should further restrict by panel, encounter, or facility assignment.
- Denials and chart opens are audit-logged (no clinical note body in the trail).
- Prefer opaque forbid messages; never leak whether another patient_id exists to patients.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.auth.oidc import AuthPrincipal
from app.auth.rbac import (
    ROLE_ADMIN,
    ROLE_PATIENT,
    ROLE_RESIDENT,
    ROLE_SENIOR,
    ROLE_STAFF,
    has_any_role,
    principal_roles,
)
from app.core.exceptions import AppError

_PATIENT_CODE = re.compile(r"^PAT-\d{6}$")

ROLES_CARE_TEAM = (ROLE_STAFF, ROLE_RESIDENT, ROLE_SENIOR, ROLE_ADMIN)
ROLES_CHART_READ = (ROLE_PATIENT, ROLE_STAFF, ROLE_RESIDENT, ROLE_SENIOR, ROLE_ADMIN)


def linked_patient_id(principal: AuthPrincipal | None) -> str | None:
    """Patient record code bound to the token (claim or subject)."""
    if principal is None:
        return None
    claims = getattr(principal, "raw_claims", None) or {}
    for key in ("patient_id", "healthevidence_patient_id", "linked_patient_id"):
        raw = claims.get(key)
        if isinstance(raw, str) and _PATIENT_CODE.fullmatch(raw.strip().upper()):
            return raw.strip().upper()
    # Direct attribute when principal was hydrated with patient_id
    attr = getattr(principal, "patient_id", None)
    if isinstance(attr, str) and _PATIENT_CODE.fullmatch(attr.strip().upper()):
        return attr.strip().upper()
    sub = str(getattr(principal, "subject", "") or "")
    if _PATIENT_CODE.fullmatch(sub.strip().upper()):
        return sub.strip().upper()
    return None


def is_patient_only(principal: AuthPrincipal | None) -> bool:
    """True when the principal is a patient without care-team elevation."""
    roles = principal_roles(principal)
    if not roles:
        return False
    if ROLE_ADMIN in roles or ROLE_STAFF in roles or ROLE_RESIDENT in roles or ROLE_SENIOR in roles:
        return False
    return ROLE_PATIENT in roles


def is_care_team(principal: AuthPrincipal | None) -> bool:
    return has_any_role(principal, *ROLES_CARE_TEAM)


def ensure_care_team(principal: AuthPrincipal | None) -> None:
    if is_care_team(principal):
        return
    raise AppError(
        "RBAC_FORBIDDEN",
        "This action is limited to care-team sign-ins (staff, resident, senior, or admin).",
        403,
    )


def ensure_patient_record_access(
    principal: AuthPrincipal | None,
    patient_code: str,
    *,
    session: Session | None = None,
    action: str = "chart_access",
    auth_disabled: bool = False,
    break_glass_id: str | None = None,
) -> None:
    """Enforce patient self-scope. No-op when auth is disabled (unit tests)."""
    if auth_disabled:
        return
    if principal is None:
        raise AppError("OIDC_UNAUTHORIZED", "Bearer token required.", 401)

    code = (patient_code or "").strip().upper()
    if not _PATIENT_CODE.fullmatch(code):
        raise AppError("PATIENT_NOT_FOUND", "Patient was not found.", 404)

    if is_care_team(principal):
        if session is not None:
            from app.db.repository import get_patient_by_code
            from app.services.org_scope import ensure_org_patient_access

            patient = get_patient_by_code(session, code)
            if patient is None:
                raise AppError("PATIENT_NOT_FOUND", "Patient was not found.", 404)
            try:
                ensure_org_patient_access(
                    session,
                    principal,
                    patient,
                    break_glass_id=break_glass_id,
                )
            except AppError as exc:
                if getattr(exc, "error_code", "") in {
                    "ORG_SCOPE_FORBIDDEN",
                    "ORG_SCOPE_REQUIRED",
                    "BREAK_GLASS_REQUIRED",
                    "BREAK_GLASS_INVALID",
                    "BREAK_GLASS_MISMATCH",
                    "BREAK_GLASS_EXPIRED",
                }:
                    _audit(
                        session,
                        action="patient_scope_denied",
                        actor=_actor(principal),
                        resource_id=code,
                        status="denied",
                        detail=str(getattr(exc, "error_code", "org_scope")),
                    )
                raise
        _audit(
            session,
            action=action,
            actor=_actor(principal),
            resource_id=code,
            status="allowed",
            detail="care_team" if not break_glass_id else "care_team_break_glass",
        )
        return

    if not is_patient_only(principal):
        raise AppError(
            "RBAC_FORBIDDEN",
            "Signed-in role cannot access patient records.",
            403,
        )

    linked = linked_patient_id(principal)
    if not linked:
        raise AppError(
            "PATIENT_LINK_REQUIRED",
            "Patient sign-in requires a linked patient_id on the token.",
            403,
        )
    if linked != code:
        _audit(
            session,
            action="patient_scope_denied",
            actor=_actor(principal),
            resource_id=code,
            status="denied",
            detail=f"linked={linked}",
        )
        raise AppError(
            "PATIENT_SCOPE_FORBIDDEN",
            "You can only access your own health record.",
            403,
        )
    _audit(
        session,
        action=action,
        actor=_actor(principal),
        resource_id=code,
        status="allowed",
        detail="self",
    )


def ensure_patient_write_target(
    principal: AuthPrincipal | None,
    patient_code: str | None,
    *,
    session: Session | None = None,
    auth_disabled: bool = False,
) -> str | None:
    """For ingest/write: patients may only target their linked record; care team respects org."""
    if auth_disabled or principal is None:
        return patient_code
    if is_care_team(principal):
        if session is not None and patient_code:
            from app.db.repository import get_patient_by_code
            from app.services.org_scope import ensure_org_patient_access

            code = patient_code.strip().upper()
            patient = get_patient_by_code(session, code)
            if patient is None:
                raise AppError("PATIENT_NOT_FOUND", "Patient was not found.", 404)
            ensure_org_patient_access(session, principal, patient)
        return patient_code
    if not is_patient_only(principal):
        raise AppError("RBAC_FORBIDDEN", "Signed-in role cannot write chart data.", 403)
    linked = linked_patient_id(principal)
    if not linked:
        raise AppError(
            "PATIENT_LINK_REQUIRED",
            "Patient sign-in requires a linked patient_id on the token.",
            403,
        )
    if patient_code and patient_code.strip().upper() != linked:
        _audit(
            session,
            action="patient_scope_denied",
            actor=_actor(principal),
            resource_id=patient_code.strip().upper(),
            status="denied",
            detail=f"write linked={linked}",
        )
        raise AppError(
            "PATIENT_SCOPE_FORBIDDEN",
            "You can only add notes to your own health record.",
            403,
        )
    return linked


def filter_patient_list_for_principal(
    principal: AuthPrincipal | None,
    *,
    auth_disabled: bool = False,
) -> str | None:
    """If patient-only, return the sole patient_id they may list; else None (all)."""
    if auth_disabled or principal is None:
        return None
    if is_care_team(principal):
        return None
    if is_patient_only(principal):
        linked = linked_patient_id(principal)
        if not linked:
            raise AppError(
                "PATIENT_LINK_REQUIRED",
                "Patient sign-in requires a linked patient_id on the token.",
                403,
            )
        return linked
    raise AppError("RBAC_FORBIDDEN", "Signed-in role cannot list patients.", 403)


def _actor(principal: AuthPrincipal) -> str:
    return str(principal.subject or "unknown")[:64]


def _audit(
    session: Session | None,
    *,
    action: str,
    actor: str,
    resource_id: str,
    status: str,
    detail: str,
) -> None:
    if session is None:
        return
    from app.services.audit import record_audit

    # Denied / break attempts must survive request rollback (AppError paths).
    if status in {"denied", "forbidden"}:
        from sqlalchemy.orm import sessionmaker

        factory = sessionmaker(
            bind=session.get_bind(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        audit_session = factory()
        try:
            record_audit(
                audit_session,
                action=action,
                actor=actor,
                resource_type="patient",
                resource_id=resource_id[:64],
                status=status,
                detail=detail,
            )
            audit_session.commit()
        except Exception:  # noqa: BLE001 — never block the forbid path
            audit_session.rollback()
        finally:
            audit_session.close()
        return

    record_audit(
        session,
        action=action,
        actor=actor,
        resource_type="patient",
        resource_id=resource_id[:64],
        status=status,
        detail=detail,
    )


def claim_patient_id_from_payload(raw: Any) -> str | None:
    if isinstance(raw, str) and _PATIENT_CODE.fullmatch(raw.strip().upper()):
        return raw.strip().upper()
    return None
