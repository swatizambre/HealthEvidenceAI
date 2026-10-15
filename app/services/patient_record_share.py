"""Emergency card, share links, and family/caregiver stubs."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.models.entities import CareRelationship, EmergencyProfile, Medication, Patient, RecordShare
from app.services.audit import record_audit
from app.services.records import require_patient

_SHARE_SCOPES = frozenset(
    {"emergency", "medications", "allergies", "conditions", "labs", "timeline"}
)


def _now() -> datetime:
    return datetime.now(UTC)


def _next_code(session: Session, model: type[Any], field: str, prefix: str) -> str:
    rows: list[Any] = list(session.scalars(select(model)).all())
    existing = {str(getattr(row, field)) for row in rows}
    for index in range(1, 10_000):
        code = f"{prefix}-{index:06d}"
        if code not in existing:
            return code
    raise AppError("CODE_EXHAUSTED", f"Could not allocate {prefix} code.", 500)


def get_or_create_emergency_profile(session: Session, patient: Patient) -> EmergencyProfile:
    profile = session.scalar(
        select(EmergencyProfile).where(EmergencyProfile.patient_id == patient.id)
    )
    if profile is not None:
        return profile
    profile = EmergencyProfile(patient_id=patient.id)
    session.add(profile)
    session.flush()
    return profile


def emergency_card_payload(
    session: Session, patient_id: str, *, actor: str, record_view: bool = False
) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    profile = get_or_create_emergency_profile(session, patient)
    meds = list(
        session.scalars(
            select(Medication)
            .where(Medication.patient_id == patient.id)
            .order_by(Medication.started_at.desc())
        ).all()
    )
    allergies = [
        item
        for item in (patient.conditions or [])
        if "allerg" in str(item).lower() or "hypersens" in str(item).lower()
    ]
    conditions = [item for item in (patient.conditions or []) if item not in allergies]
    if record_view:
        record_audit(
            session,
            action="emergency_card_viewed",
            actor=actor,
            resource_type="patient",
            resource_id=patient.patient_code,
            status="ok",
            detail="emergency_card",
        )
        session.flush()
    return {
        "patient_id": patient.patient_code,
        "display_name": patient.synthetic_name,
        "sex": patient.sex,
        "date_of_birth": patient.birth_date.isoformat(),
        "blood_group": profile.blood_group or "",
        "allergies": allergies[:20],
        "conditions": conditions[:20],
        "medications": [
            {"name": med.name, "dose": med.dose, "status": med.status} for med in meds[:20]
        ],
        "implants": profile.implants or "",
        "emergency_contacts": profile.emergency_contacts or [],
        "notes": profile.notes or "",
        "show_on_lock_screen": bool(profile.show_on_lock_screen),
        "qr_payload": f"HE-EMERG:{patient.patient_code}",
        "disclaimer": (
            "Emergency summary for continuity only. Not a diagnosis. "
            "Confirm allergies and medicines with the patient or chart."
        ),
    }


def update_emergency_profile(
    session: Session, patient_id: str, patch: dict[str, Any], *, actor: str
) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    profile = get_or_create_emergency_profile(session, patient)
    if "blood_group" in patch and patch["blood_group"] is not None:
        profile.blood_group = str(patch["blood_group"])[:16]
    if "implants" in patch and patch["implants"] is not None:
        profile.implants = str(patch["implants"])[:2000]
    if "notes" in patch and patch["notes"] is not None:
        profile.notes = str(patch["notes"])[:2000]
    if "show_on_lock_screen" in patch and patch["show_on_lock_screen"] is not None:
        profile.show_on_lock_screen = bool(patch["show_on_lock_screen"])
    if "emergency_contacts" in patch and patch["emergency_contacts"] is not None:
        contacts = patch["emergency_contacts"]
        if not isinstance(contacts, list):
            raise AppError("VALIDATION_ERROR", "emergency_contacts must be a list.", 422)
        cleaned: list[dict[str, str]] = []
        for item in contacts[:8]:
            if not isinstance(item, dict):
                continue
            cleaned.append(
                {
                    "name": str(item.get("name") or "")[:80],
                    "phone": str(item.get("phone") or "")[:40],
                    "relation": str(item.get("relation") or "")[:40],
                }
            )
        profile.emergency_contacts = cleaned
    record_audit(
        session,
        action="emergency_card_updated",
        actor=actor,
        resource_type="patient",
        resource_id=patient.patient_code,
        status="ok",
        detail="emergency_card",
    )
    session.flush()
    return emergency_card_payload(session, patient_id, actor=actor, record_view=False)


def create_share(
    session: Session,
    patient_id: str,
    *,
    scopes: list[str],
    hours: int,
    label: str,
    actor: str,
) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    hours = max(1, min(int(hours or 24), 24 * 14))
    wanted = [item for item in scopes if item in _SHARE_SCOPES] or ["emergency", "medications", "allergies"]
    share = RecordShare(
        share_code=_next_code(session, RecordShare, "share_code", "SHR"),
        token=secrets.token_urlsafe(24),
        patient_id=patient.id,
        label=(label or "Doctor share")[:160],
        scopes=wanted,
        expires_at=_now() + timedelta(hours=hours),
        created_by=actor[:120],
    )
    session.add(share)
    record_audit(
        session,
        action="record_share_created",
        actor=actor,
        resource_type="record_share",
        resource_id=share.share_code,
        status="ok",
        detail=f"hours={hours}",
    )
    session.flush()
    return share_out(share, include_token=True)


def list_shares(session: Session, patient_id: str) -> list[dict[str, Any]]:
    patient = require_patient(session, patient_id)
    rows = session.scalars(
        select(RecordShare)
        .where(RecordShare.patient_id == patient.id)
        .order_by(RecordShare.created_at.desc())
    ).all()
    return [share_out(row, include_token=False) for row in rows]


def revoke_share(session: Session, patient_id: str, share_code: str, *, actor: str) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    share = session.scalar(
        select(RecordShare).where(
            RecordShare.patient_id == patient.id,
            RecordShare.share_code == share_code,
        )
    )
    if share is None:
        raise NotFoundError("SHARE_NOT_FOUND", f"Share {share_code} not found.")
    if share.revoked_at is None:
        share.revoked_at = _now()
        record_audit(
            session,
            action="record_share_revoked",
            actor=actor,
            resource_type="record_share",
            resource_id=share.share_code,
            status="ok",
            detail="",
        )
        session.flush()
    return share_out(share, include_token=False)


def resolve_public_share(session: Session, token: str) -> dict[str, Any]:
    share = session.scalar(select(RecordShare).where(RecordShare.token == token))
    if share is None:
        raise NotFoundError("SHARE_NOT_FOUND", "Share link not found.")
    if share.revoked_at is not None:
        raise AppError("SHARE_REVOKED", "This share link was revoked.", 410)
    if share.expires_at.replace(tzinfo=share.expires_at.tzinfo or UTC) < _now():
        raise AppError("SHARE_EXPIRED", "This share link has expired.", 410)
    patient = session.get(Patient, share.patient_id)
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "Patient not found for share.")
    share.view_count = int(share.view_count or 0) + 1
    share.last_viewed_at = _now()
    record_audit(
        session,
        action="record_share_viewed",
        actor="share-link",
        resource_type="record_share",
        resource_id=share.share_code,
        status="ok",
        detail=f"views={share.view_count}",
    )
    session.flush()
    card = emergency_card_payload(session, patient.patient_code, actor="share-link", record_view=False)
    scopes = set(share.scopes or [])
    summary: dict[str, Any] = {
        "share_code": share.share_code,
        "label": share.label,
        "scopes": list(share.scopes or []),
        "expires_at": share.expires_at.isoformat(),
        "patient_id": patient.patient_code,
        "display_name": patient.synthetic_name,
        "disclaimer": card["disclaimer"],
    }
    if "emergency" in scopes or "allergies" in scopes:
        summary["allergies"] = card["allergies"]
        summary["blood_group"] = card["blood_group"]
        summary["implants"] = card["implants"]
        summary["emergency_contacts"] = card["emergency_contacts"]
    if "medications" in scopes:
        summary["medications"] = card["medications"]
    if "conditions" in scopes:
        summary["conditions"] = card["conditions"]
    return summary


def share_out(share: RecordShare, *, include_token: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "share_id": share.share_code,
        "label": share.label,
        "scopes": list(share.scopes or []),
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
        "view_count": int(share.view_count or 0),
        "last_viewed_at": share.last_viewed_at.isoformat() if share.last_viewed_at else None,
        "created_at": share.created_at.isoformat() if share.created_at else None,
    }
    if include_token:
        payload["token"] = share.token
        payload["path"] = f"/share/{share.token}"
    return payload


def list_care_relationships(session: Session, patient_id: str) -> list[dict[str, Any]]:
    patient = require_patient(session, patient_id)
    rows = session.scalars(
        select(CareRelationship)
        .where(CareRelationship.patient_id == patient.id)
        .order_by(CareRelationship.created_at.desc())
    ).all()
    return [care_out(row) for row in rows]


def create_care_relationship(
    session: Session,
    patient_id: str,
    *,
    related_display_name: str,
    relationship_type: str,
    related_patient_code: str | None,
    access_level: str,
    actor: str,
) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    name = (related_display_name or "").strip()
    if len(name) < 2:
        raise AppError("VALIDATION_ERROR", "related_display_name is required.", 422)
    rel = CareRelationship(
        relationship_code=_next_code(session, CareRelationship, "relationship_code", "FAM"),
        patient_id=patient.id,
        related_display_name=name[:160],
        relationship_type=(relationship_type or "caregiver")[:32],
        related_patient_code=(related_patient_code or None),
        access_level=(access_level or "view")[:32],
    )
    session.add(rel)
    record_audit(
        session,
        action="care_relationship_created",
        actor=actor,
        resource_type="care_relationship",
        resource_id=rel.relationship_code,
        status="ok",
        detail=rel.relationship_type,
    )
    session.flush()
    return care_out(rel)


def care_out(row: CareRelationship) -> dict[str, Any]:
    return {
        "relationship_id": row.relationship_code,
        "related_display_name": row.related_display_name,
        "relationship_type": row.relationship_type,
        "related_patient_code": row.related_patient_code,
        "access_level": row.access_level,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
