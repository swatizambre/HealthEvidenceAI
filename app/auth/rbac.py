"""Product RBAC for hospital desks and patient self-access.

Canonical roles (JWT / OIDC):
- patient — own lifelong record + self-reported visit notes (no PA HITL / packet prep)
- staff — records, PA desk (prep + visit notes)
- resident — junior doctor (prep, visit notes, evidence check; cannot final-sign HITL)
- senior_clinician — consultant / attending (HITL acknowledge / send back)
- admin — facility ops; all care-team actions

API field names may still say encounter (FHIR); product UI says \"visit note\".
"""

from __future__ import annotations

from app.auth.oidc import AuthPrincipal
from app.core.exceptions import AppError

ROLE_PATIENT = "patient"
ROLE_STAFF = "staff"
ROLE_RESIDENT = "resident"
ROLE_SENIOR = "senior_clinician"
ROLE_ADMIN = "admin"

ROLES_CHART_WRITE = (ROLE_PATIENT, ROLE_STAFF, ROLE_RESIDENT, ROLE_SENIOR)
ROLES_PACKET_PREP = (ROLE_STAFF, ROLE_RESIDENT, ROLE_SENIOR)
ROLES_EVIDENCE_CHECK = (ROLE_STAFF, ROLE_RESIDENT, ROLE_SENIOR)
ROLES_HITL = (ROLE_SENIOR,)
# Recording consent is a care-team desk act (patients withdraw, they do not self-record).
ROLES_CONSENT_RECORD = (ROLE_STAFF, ROLE_RESIDENT, ROLE_SENIOR)
# Facility privacy / grievance desk (admin always passes has_any_role).
ROLES_PRIVACY_DESK = (ROLE_STAFF, ROLE_ADMIN)

_ALIASES: dict[str, str] = {
    "patient": ROLE_PATIENT,
    "self": ROLE_PATIENT,
    "member": ROLE_PATIENT,
    "senior_clinician": ROLE_SENIOR,
    "senior": ROLE_SENIOR,
    "clinician": ROLE_SENIOR,
    "consultant": ROLE_SENIOR,
    "attending": ROLE_SENIOR,
    "specialist": ROLE_SENIOR,
    "reviewer": ROLE_SENIOR,
    "mo": ROLE_SENIOR,
    "medical_officer": ROLE_SENIOR,
    "resident": ROLE_RESIDENT,
    "junior_doctor": ROLE_RESIDENT,
    "junior": ROLE_RESIDENT,
    "trainee": ROLE_RESIDENT,
    "pg": ROLE_RESIDENT,
    "registrar": ROLE_RESIDENT,
    "staff": ROLE_STAFF,
    "coordinator": ROLE_STAFF,
    "pa_staff": ROLE_STAFF,
    "records": ROLE_STAFF,
    "clerk": ROLE_STAFF,
    "nurse": ROLE_STAFF,
    "nursing": ROLE_STAFF,
    "admin": ROLE_ADMIN,
    "facility_admin": ROLE_ADMIN,
}


def normalize_roles(roles: tuple[str, ...] | list[str]) -> frozenset[str]:
    out: set[str] = set()
    for raw in roles:
        key = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
        mapped = _ALIASES.get(key)
        if mapped:
            out.add(mapped)
    return frozenset(out)


def principal_roles(principal: AuthPrincipal | None) -> frozenset[str]:
    if principal is None:
        return frozenset()
    return normalize_roles(principal.roles)


def has_any_role(principal: AuthPrincipal | None, *needed: str) -> bool:
    have = principal_roles(principal)
    if ROLE_ADMIN in have:
        return True
    want = normalize_roles(needed)
    return bool(have.intersection(want))


def ensure_any_role(principal: AuthPrincipal | None, *needed: str) -> None:
    if has_any_role(principal, *needed):
        return
    raise AppError(
        "RBAC_FORBIDDEN",
        (
            f"This action requires one of: {', '.join(sorted(normalize_roles(needed)))}. "
            f"Current roles: {sorted(principal_roles(principal)) or ['none']}."
        ),
        403,
    )


def ensure_senior_hitl(principal: AuthPrincipal | None) -> None:
    """Final evidence-pack acknowledgment requires senior_clinician (not staff/resident/admin alone)."""
    if ROLE_SENIOR in principal_roles(principal):
        return
    raise AppError(
        "RBAC_FORBIDDEN",
        (
            "Senior clinician sign-off is required to acknowledge or return an evidence pack. "
            f"Current roles: {sorted(principal_roles(principal)) or ['none']}."
        ),
        403,
    )
