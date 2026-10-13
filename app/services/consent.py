"""Stored consent records (DPDP Act 2023 s.5-6 notice + consent; HIPAA authorization trail).

A consent row is the durable artefact behind every PHI ingest: who granted it, for which
purpose, under which notice version, how it was captured, and whether it was withdrawn.
Rows are never deleted — withdrawal stamps ``revoked_at`` so past processing stays explainable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.db.repository import next_public_code
from app.models import ConsentRecord, Patient
from app.schemas.api import ConsentCreate, ConsentListResponse, ConsentOut
from app.services.audit import record_audit
from app.services.pseudonym import staff_reference

CONSENT_PURPOSES: tuple[str, ...] = ("prior_auth_evidence", "continuity_of_care", "research_trial")
CONSENT_METHODS: tuple[str, ...] = ("written", "electronic", "verbal_witnessed")
# Purposes that lawfully cover storing an OPD visit packet on the chart.
INGEST_PURPOSES: tuple[str, ...] = ("prior_auth_evidence", "continuity_of_care")
PRACTICE_NOTICE_VERSION = "synthetic-practice"
# Desk / tablet clocks drift; tolerate small future skew on granted_at.
_CLOCK_SKEW = timedelta(minutes=5)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def is_consent_active(record: ConsentRecord, *, now: datetime | None = None) -> bool:
    """Active = granted, not withdrawn, not expired, and granted_at not in the future."""
    moment = now or datetime.now(UTC)
    if record.revoked_at is not None:
        return False
    expires = _as_utc(record.expires_at)
    if expires is not None and expires <= moment:
        return False
    granted = _as_utc(record.granted_at)
    return granted is None or granted <= moment


def _org_matches(record: ConsentRecord, org_id: str | None) -> bool:
    # A consent bound to a facility only covers that facility (DPDP: per Data Fiduciary).
    # Unbound rows (org_id NULL — auth-off laptop desks) cover any caller.
    if record.org_id is None or org_id is None:
        return True
    return record.org_id == org_id


def active_consent(
    session: Session,
    patient_id: str,
    purpose: str,
    org_id: str | None = None,
    *,
    now: datetime | None = None,
) -> ConsentRecord | None:
    """Newest active consent for patient (internal id) + purpose, scoped to org when given."""
    rows = session.scalars(
        select(ConsentRecord)
        .where(
            ConsentRecord.patient_id == patient_id,
            ConsentRecord.purpose == purpose,
            ConsentRecord.revoked_at.is_(None),
        )
        .order_by(ConsentRecord.granted_at.desc(), ConsentRecord.consent_code.desc())
    ).all()
    for row in rows:
        if _org_matches(row, org_id) and is_consent_active(row, now=now):
            return row
    return None


def get_consent_by_code(session: Session, consent_code: str) -> ConsentRecord | None:
    return session.scalar(
        select(ConsentRecord).where(ConsentRecord.consent_code == consent_code.strip().upper())
    )


def list_consents_for_patient(session: Session, patient_id: str) -> list[ConsentRecord]:
    return list(
        session.scalars(
            select(ConsentRecord)
            .where(ConsentRecord.patient_id == patient_id)
            .order_by(ConsentRecord.granted_at.desc(), ConsentRecord.consent_code.desc())
        ).all()
    )


def mask_staff_subject(subject: str | None) -> str:
    """Patient-facing label for a staff subject (no personal email / username)."""
    raw = (subject or "").strip()
    if not raw:
        return ""
    if raw.upper().startswith("PAT-") or raw == "practice-attestation":
        return raw
    return f"Care team · ref {staff_reference(raw)}"


def consent_out(
    record: ConsentRecord, patient_code: str, *, mask_staff: bool = False
) -> ConsentOut:
    granted = _as_utc(record.granted_at) or datetime.now(UTC)
    created = _as_utc(record.created_at) or granted
    return ConsentOut(
        consent_id=record.consent_code,
        patient_id=patient_code,
        purpose=record.purpose,
        scope=record.scope or "",
        method=record.method,
        language=record.language or "en",
        notice_version=record.notice_version,
        granted_by_name=record.granted_by_name,
        recorded_by=(
            mask_staff_subject(record.recorded_by) if mask_staff else record.recorded_by
        ),
        granted_at=granted,
        expires_at=_as_utc(record.expires_at),
        revoked_at=_as_utc(record.revoked_at),
        revoked_reason=record.revoked_reason or "",
        evidence_ref=record.evidence_ref or "",
        created_at=created,
        active=is_consent_active(record),
    )


def consent_list_response(
    session: Session, patient: Patient, *, mask_staff: bool = False
) -> ConsentListResponse:
    rows = list_consents_for_patient(session, patient.id)
    return ConsentListResponse(
        patient_id=patient.patient_code,
        consents=[consent_out(row, patient.patient_code, mask_staff=mask_staff) for row in rows],
        total=len(rows),
    )


def record_consent(
    session: Session,
    patient: Patient,
    payload: ConsentCreate,
    *,
    recorded_by: str,
    org_id: str | None = None,
    now: datetime | None = None,
    via: str = "consent_api",
) -> ConsentRecord:
    """Persist one consent and audit it (no free-text scope in the audit trail)."""
    moment = now or datetime.now(UTC)
    granted = _as_utc(payload.granted_at) or moment
    expires = _as_utc(payload.expires_at)
    if expires is not None and expires <= granted:
        raise AppError(
            "CONSENT_INVALID",
            "expires_at must be after granted_at.",
            422,
        )
    if granted > moment + _CLOCK_SKEW:
        raise AppError("CONSENT_INVALID", "granted_at cannot be in the future.", 422)
    granted = min(granted, moment)
    record = ConsentRecord(
        id=str(uuid4()),
        consent_code=next_public_code(session, ConsentRecord.consent_code, "CNS"),
        patient_id=patient.id,
        org_id=org_id if org_id is not None else getattr(patient, "org_id", None),
        purpose=payload.purpose,
        scope=payload.scope,
        method=payload.method,
        language=payload.language,
        notice_version=payload.notice_version,
        granted_by_name=payload.granted_by_name,
        recorded_by=(recorded_by or "care-team")[:120],
        granted_at=granted,
        expires_at=expires,
        revoked_at=None,
        revoked_reason="",
        evidence_ref=payload.evidence_ref,
        created_at=moment,
    )
    session.add(record)
    session.flush()
    record_audit(
        session,
        action="consent_recorded",
        actor=(recorded_by or "care-team")[:64],
        resource_type="consent",
        resource_id=record.consent_code,
        status="created",
        detail=(
            f"patient={patient.patient_code};purpose={record.purpose};method={record.method};"
            f"notice={record.notice_version};via={via}"
        ),
    )
    return record


def revoke_consent(
    session: Session,
    patient: Patient,
    consent_code: str,
    *,
    reason: str,
    revoked_by: str,
    now: datetime | None = None,
) -> ConsentRecord:
    """Withdraw consent (DPDP s.6(4)). Idempotent refusal when already withdrawn."""
    record = get_consent_by_code(session, consent_code)
    if record is None or record.patient_id != patient.id:
        raise NotFoundError("CONSENT_NOT_FOUND", "Consent record was not found.")
    if record.revoked_at is not None:
        raise AppError("CONSENT_ALREADY_REVOKED", "This consent was already withdrawn.", 409)
    record.revoked_at = now or datetime.now(UTC)
    record.revoked_reason = reason[:500]
    record.revoked_by = (revoked_by or "unknown")[:120]
    session.flush()
    record_audit(
        session,
        action="consent_revoked",
        actor=(revoked_by or "unknown")[:64],
        resource_type="consent",
        resource_id=record.consent_code,
        status="revoked",
        detail=f"patient={patient.patient_code};purpose={record.purpose}",
    )
    return record


def require_ingest_consent(
    session: Session,
    patient: Patient,
    consent_code: str,
    *,
    org_id: str | None = None,
) -> ConsentRecord:
    """Validate a referenced consent covers storing an OPD packet for this patient."""
    record = get_consent_by_code(session, consent_code)
    if record is None or record.patient_id != patient.id:
        raise consent_required_error(
            f"Consent {consent_code} was not found for patient {patient.patient_code}."
        )
    if record.purpose not in INGEST_PURPOSES:
        raise consent_required_error(
            f"Consent {consent_code} is for purpose '{record.purpose}', which does not cover "
            "storing visit records. Use a prior_auth_evidence or continuity_of_care consent."
        )
    if not _org_matches(record, org_id):
        raise consent_required_error(
            f"Consent {consent_code} was granted to a different facility."
        )
    if not is_consent_active(record):
        raise consent_required_error(
            f"Consent {consent_code} is withdrawn or expired. Record a fresh consent first."
        )
    return record


def consent_required_error(message: str) -> AppError:
    return AppError("CONSENT_REQUIRED", message, 403)


def ensure_practice_consent(
    session: Session,
    patient: Patient,
    *,
    recorded_by: str,
    org_id: str | None = None,
    now: datetime | None = None,
) -> ConsentRecord:
    """Practice/synthetic desks: store the checkbox attestation as a consent row (reused)."""
    existing = active_consent(session, patient.id, "prior_auth_evidence", org_id, now=now)
    if existing is not None:
        return existing
    return record_consent(
        session,
        patient,
        ConsentCreate(
            purpose="prior_auth_evidence",
            scope="Synthetic / practice OPD packets (checkbox attestation).",
            method="electronic",
            language="en",
            notice_version=PRACTICE_NOTICE_VERSION,
            granted_by_name="practice-attestation",
        ),
        recorded_by=recorded_by,
        org_id=org_id,
        now=now,
        via="practice_checkbox",
    )
