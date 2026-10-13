"""Multi-organization (facility tenant) helpers — India rural→urban demo chain."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Organization
from app.services.india_desk import india_org_seeds

_PLACEHOLDER_NAMES = frozenset(
    {
        "Demo Health System",
        "Northside Community Clinic",
    }
)


def ensure_default_organization(session: Session) -> Organization:
    """Create or return the primary demo org (urban multispecialty by default)."""
    settings = get_settings()
    code = (settings.default_org_code or "ORG-000001").strip() or "ORG-000001"
    seeds = {item["org_code"]: item for item in india_org_seeds()}
    seed = seeds.get(code) or {
        "org_code": code,
        "name": (settings.default_org_name or "Krishna Multispecialty Hospital, Pune")[:160],
        "facility_type": "multispecialty",
    }
    existing = session.scalar(select(Organization).where(Organization.org_code == code))
    if existing is not None:
        if existing.name in _PLACEHOLDER_NAMES:
            existing.name = str(seed["name"])[:160]
            existing.facility_type = str(seed["facility_type"])[:64]
            session.flush()
        return existing
    org = Organization(
        org_code=code,
        name=str(seed["name"])[:160],
        facility_type=str(seed["facility_type"])[:64],
        active=True,
    )
    session.add(org)
    session.flush()
    return org


def ensure_secondary_organization(session: Session) -> Organization:
    """PHC tenant so rural desk + wrong-org empty queue are demonstrable."""
    return _ensure_seed_org(session, "ORG-000002")


def ensure_pilot_organizations(session: Session) -> tuple[Organization, Organization]:
    """Default urban hospital + PHC for multi-tenant / referral demos."""
    primary = ensure_default_organization(session)
    for item in india_org_seeds():
        _ensure_seed_org(session, str(item["org_code"]))
    secondary = _ensure_seed_org(session, "ORG-000002")
    return primary, secondary


def _ensure_seed_org(session: Session, org_code: str) -> Organization:
    seeds = {item["org_code"]: item for item in india_org_seeds()}
    seed = seeds.get(org_code)
    if seed is None:
        raise ValueError(f"Unknown India org seed: {org_code}")
    existing = session.scalar(select(Organization).where(Organization.org_code == org_code))
    if existing is not None:
        if existing.name in _PLACEHOLDER_NAMES:
            existing.name = str(seed["name"])[:160]
            existing.facility_type = str(seed["facility_type"])[:64]
            session.flush()
        return existing
    org = Organization(
        org_code=str(seed["org_code"]),
        name=str(seed["name"])[:160],
        facility_type=str(seed["facility_type"])[:64],
        active=True,
    )
    session.add(org)
    session.flush()
    return org


def list_organizations(session: Session) -> list[Organization]:
    ensure_pilot_organizations(session)
    return list(
        session.scalars(
            select(Organization).where(Organization.active.is_(True)).order_by(Organization.org_code)
        ).all()
    )


def org_code_for_facility(facility_type: str) -> str:
    """Map desk facility mode to a demo org code when available."""
    key = (facility_type or "").strip().lower()
    for item in india_org_seeds():
        if item["facility_type"] == key:
            return str(item["org_code"])
    return "ORG-000001"
