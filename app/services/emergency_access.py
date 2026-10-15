"""No-login emergency link (QR), access events and family alerts.

The patient's emergency card carries a QR code for a secret link. Anyone who
finds the patient (a doctor abroad, a bystander, an ambulance crew) can open it
without an account and sees only the emergency summary. Each opening is
recorded as an access event; the patient and their linked family see it as an
alert, with the place the opener chose to share.

Only in-app alerts are delivered here. SMS or WhatsApp delivery needs a provider
and is logged as not configured rather than pretended.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, NotFoundError
from app.models.entities import (
    CareRelationship,
    EmergencyAccessEvent,
    EmergencyProfile,
    Medication,
    Patient,
)
from app.services import qr
from app.services.audit import record_audit
from app.services.patient_record_share import get_or_create_emergency_profile
from app.services.records import require_patient

logger = logging.getLogger("healthevidence.emergency")

# A reload by the same browser within this window reuses the event instead of
# raising a second alert.
REOPEN_WINDOW = timedelta(minutes=10)
# The opener can add where they are for this long after opening.
PLACE_WINDOW = timedelta(hours=2)
_INACTIVE = frozenset({"stopped", "completed", "inactive", "discontinued", "cancelled"})

PUBLIC_DISCLAIMER = (
    "Emergency summary shared by the patient. Confirm allergies and medicines when you can. "
    "Not a diagnosis."
)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _new_token() -> str:
    return secrets.token_urlsafe(16)


def ensure_public_token(session: Session, profile: EmergencyProfile) -> str:
    if not profile.public_token:
        profile.public_token = _new_token()
        session.flush()
    return profile.public_token


def emergency_url(token: str) -> str:
    return f"{get_settings().public_app_base()}/e/{token}"


def link_payload(session: Session, patient: Patient) -> dict[str, Any]:
    """Link, QR matrix and alert setting for the owner's own card."""
    profile = get_or_create_emergency_profile(session, patient)
    url = emergency_url(ensure_public_token(session, profile))
    return {
        "emergency_url": url,
        "qr_modules": qr.encode(url),
        "alert_family": bool(profile.alert_family if profile.alert_family is not None else True),
    }


def rotate_public_token(session: Session, patient_id: str, *, actor: str) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    profile = get_or_create_emergency_profile(session, patient)
    profile.public_token = _new_token()
    record_audit(
        session,
        action="emergency_link_rotated",
        actor=actor,
        resource_type="patient",
        resource_id=patient.patient_code,
        status="ok",
        detail="old QR codes stop working",
    )
    session.flush()
    return link_payload(session, patient)


def _profile_for_token(session: Session, token: str) -> EmergencyProfile:
    clean = (token or "").strip()
    profile = (
        session.scalar(select(EmergencyProfile).where(EmergencyProfile.public_token == clean))
        if 16 <= len(clean) <= 48
        else None
    )
    if profile is None:
        raise NotFoundError("EMERGENCY_LINK_NOT_FOUND", "This emergency card link is not valid.")
    return profile


def _age(birth: Any, today: datetime) -> int | None:
    try:
        years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    except AttributeError:
        return None
    return years if years >= 0 else None


def _next_event_code() -> str:
    return f"EMA-{secrets.token_hex(5).upper()}"


def _caregiver_codes(session: Session, patient: Patient) -> list[str]:
    rows = session.scalars(
        select(CareRelationship).where(CareRelationship.patient_id == patient.id)
    ).all()
    return sorted({row.related_patient_code for row in rows if row.related_patient_code})


def open_public_card(session: Session, token: str, *, user_agent: str = "") -> dict[str, Any]:
    """Return the emergency summary for a QR link and record the opening."""
    profile = _profile_for_token(session, token)
    patient = session.get(Patient, profile.patient_id)
    if patient is None:
        raise NotFoundError("EMERGENCY_LINK_NOT_FOUND", "This emergency card link is not valid.")
    now = _now()
    agent = (user_agent or "")[:160]
    recent = session.scalar(
        select(EmergencyAccessEvent)
        .where(
            EmergencyAccessEvent.patient_id == patient.id,
            EmergencyAccessEvent.user_agent == agent,
            EmergencyAccessEvent.opened_at >= now - REOPEN_WINDOW,
        )
        .order_by(EmergencyAccessEvent.opened_at.desc())
    )
    contacts = list(profile.emergency_contacts or [])
    caregivers = _caregiver_codes(session, patient)
    alert_family = bool(profile.alert_family if profile.alert_family is not None else True)
    if recent is None:
        recent = EmergencyAccessEvent(
            event_code=_next_event_code(),
            patient_id=patient.id,
            opened_at=now,
            user_agent=agent,
        )
        session.add(recent)
        record_audit(
            session,
            action="emergency_card_opened",
            actor="emergency-link",
            resource_type="patient",
            resource_id=patient.patient_code,
            status="ok",
            detail=f"event={recent.event_code}",
        )
        logger.info(
            "emergency_card_opened",
            extra={
                "patient_id": patient.patient_code,
                "event": recent.event_code,
                "alert_family": alert_family,
                "in_app_recipients": 1 + len(caregivers),
                "sms_whatsapp": "not_configured",
                "contacts": len(contacts),
            },
        )
        session.flush()

    meds = [
        {"name": med.name, "dose": med.dose}
        for med in session.scalars(
            select(Medication)
            .where(Medication.patient_id == patient.id)
            .order_by(Medication.started_at.desc())
        ).all()
        if (med.status or "").strip().lower() not in _INACTIVE
    ]
    allergies = [
        str(item)
        for item in (patient.conditions or [])
        if any(word in str(item).lower() for word in ("allerg", "hypersens", "anaphyla"))
    ]
    conditions = [str(item) for item in (patient.conditions or []) if str(item) not in allergies]
    return {
        "event_id": recent.event_code,
        "display_name": patient.synthetic_name,
        "age": _age(patient.birth_date, now),
        "sex": patient.sex,
        "blood_group": profile.blood_group or "",
        "allergies": allergies[:20],
        "conditions": conditions[:12],
        "medications": meds[:15],
        "implants": profile.implants or "",
        "notes": profile.notes or "",
        "emergency_contacts": [
            {
                "name": str(item.get("name") or ""),
                "phone": str(item.get("phone") or ""),
                "relation": str(item.get("relation") or ""),
            }
            for item in contacts[:8]
            if isinstance(item, dict)
        ],
        "family_alerted": alert_family,
        "disclaimer": PUBLIC_DISCLAIMER,
    }


def add_place(
    session: Session,
    token: str,
    event_id: str,
    *,
    place_note: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """Let the opener tell the family where the patient is (optional, short window)."""
    profile = _profile_for_token(session, token)
    event = session.scalar(
        select(EmergencyAccessEvent).where(
            EmergencyAccessEvent.event_code == event_id,
            EmergencyAccessEvent.patient_id == profile.patient_id,
        )
    )
    if event is None:
        raise NotFoundError("EMERGENCY_EVENT_NOT_FOUND", "This opening was not found.")
    if _now() - _as_utc(event.opened_at) > PLACE_WINDOW:
        raise AppError("EMERGENCY_EVENT_CLOSED", "It is too late to add a place to this opening.", 410)
    if (latitude is None) != (longitude is None):
        raise AppError("VALIDATION_ERROR", "Send both latitude and longitude, or neither.", 422)
    if latitude is not None and longitude is not None:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise AppError("VALIDATION_ERROR", "Location is out of range.", 422)
        # About 100 m: enough to find a hospital, not a house.
        event.latitude = round(latitude, 3)
        event.longitude = round(longitude, 3)
    note = " ".join((place_note or "").split())[:200]
    if note:
        event.place_note = note
    session.flush()
    return _event_out(session, event, viewer=None)


def _event_out(
    session: Session, event: EmergencyAccessEvent, *, viewer: Patient | None
) -> dict[str, Any]:
    owner = session.get(Patient, event.patient_id)
    whose = "you"
    if viewer is None or owner is None or owner.id != viewer.id:
        whose = owner.synthetic_name if owner is not None else ""
    return {
        "event_id": event.event_code,
        "patient_id": owner.patient_code if owner is not None else "",
        "whose": whose,
        "opened_at": _as_utc(event.opened_at).isoformat(),
        "place_note": event.place_note or "",
        "latitude": event.latitude,
        "longitude": event.longitude,
        "acknowledged": event.acknowledged_at is not None,
    }


def _visible_patient_ids(session: Session, viewer: Patient) -> list[str]:
    """The viewer's own card plus every card whose owner listed the viewer as family."""
    owners = session.scalars(
        select(CareRelationship.patient_id).where(
            CareRelationship.related_patient_code == viewer.patient_code
        )
    ).all()
    ids = {viewer.id}
    for owner_id in owners:
        owner_profile = session.scalar(
            select(EmergencyProfile).where(EmergencyProfile.patient_id == owner_id)
        )
        if owner_profile is None or owner_profile.alert_family is not False:
            ids.add(owner_id)
    return sorted(ids)


def list_alerts(session: Session, patient_id: str, *, limit: int = 30) -> list[dict[str, Any]]:
    viewer = require_patient(session, patient_id)
    events = session.scalars(
        select(EmergencyAccessEvent)
        .where(EmergencyAccessEvent.patient_id.in_(_visible_patient_ids(session, viewer)))
        .order_by(EmergencyAccessEvent.opened_at.desc())
        .limit(limit)
    ).all()
    return [_event_out(session, event, viewer=viewer) for event in events]


def acknowledge(session: Session, patient_id: str, event_id: str, *, actor: str) -> dict[str, Any]:
    viewer = require_patient(session, patient_id)
    event = session.scalar(
        select(EmergencyAccessEvent).where(EmergencyAccessEvent.event_code == event_id)
    )
    if event is None or event.patient_id not in _visible_patient_ids(session, viewer):
        raise NotFoundError("EMERGENCY_EVENT_NOT_FOUND", "This alert was not found.")
    if event.acknowledged_at is None:
        event.acknowledged_at = _now()
        event.acknowledged_by = actor[:120]
        session.flush()
    return _event_out(session, event, viewer=viewer)
