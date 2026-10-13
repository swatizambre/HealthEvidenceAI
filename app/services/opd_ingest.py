"""Patient-wise OPD packet ingest (Phase 1 prototype).

Accepts one encounter packet, stores patient-scoped documents, indexes chunks,
and optionally links an authorization case. Synthetic packets only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.safety import DISCLAIMER, PROTOTYPE_BANNER
from app.db.repository import (
    get_patient_by_code,
    get_policy_by_code,
    next_public_code,
)
from app.models import (
    AuthorizationCase,
    ClinicalNote,
    ConsentRecord,
    Document,
    LabResult,
    Medication,
    Patient,
    Procedure,
)
from app.schemas.api import OpdIngestRequest, OpdIngestResponse
from app.services.audit import record_audit
from app.services.consent import (
    INGEST_PURPOSES,
    consent_required_error,
    ensure_practice_consent,
    record_consent,
    require_ingest_consent,
)
from app.services.embeddings import EMBEDDING_METHOD
from app.services.indexing import index_document
from app.services.organizations import ensure_default_organization

_OPD_SOURCES = frozenset({"opd_manual", "opd_export", "his_export", "fhir_r4", "hl7_mapped"})


def ingest_opd_packet(
    session: Session,
    payload: OpdIngestRequest,
    *,
    org_id: str | None = None,
    actor: str | None = None,
) -> OpdIngestResponse:
    """Ingest one outpatient packet for a single patient.

    Consent: PHI mode requires a stored, active consent (``consent_id``) or, for a chart
    created by this ingest, an inline ``consent`` stored in the same transaction.
    Practice mode keeps the checkbox but still writes a ConsentRecord for the trail.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.allow_phi and not settings.phi_program_attested:
        raise AppError(
            "PHI_PROGRAM_REQUIRED",
            "ALLOW_PHI is set but PHI_PROGRAM_ATTESTED is false. "
            "Complete an accountable privacy program before live PHI ingest.",
            403,
        )
    if not payload.synthetic and not settings.allow_phi:
        raise AppError(
            "OPD_SYNTHETIC_REQUIRED",
            "Hospital / OPD ingest accepts synthetic or practice packets only "
            f"(set synthetic=true) until ALLOW_PHI + PHI_PROGRAM_ATTESTED. {PROTOTYPE_BANNER}",
            400,
        )
    if (
        not settings.hospital_practice_mode()
        and payload.synthetic
        and settings.is_shared_live_env()
    ):
        raise AppError(
            "OPD_LIVE_SYNTHETIC_FORBIDDEN",
            "Synthetic packets are not accepted on attested PHI live environments. "
            "Send real consented encounter payloads with synthetic=false.",
            400,
        )
    phi_mode = not settings.hospital_practice_mode()
    if phi_mode and settings.trial_expired():
        raise AppError(
            "TRIAL_ENDED",
            "The approved real-data trial period (TRIAL_END_DATE) has ended; new patient "
            "records are not accepted. Extend the approved trial or switch to practice mode.",
            403,
        )
    has_consent_ref = bool(payload.consent_id or payload.consent is not None)
    if phi_mode and not has_consent_ref:
        raise consent_required_error(
            "PHI mode: reference an active consent (consent_id) for this patient with purpose "
            "prior_auth_evidence or continuity_of_care, or include an inline consent when "
            "registering a new patient."
        )
    if not phi_mode and not payload.consent_attested and not has_consent_ref:
        raise AppError(
            "OPD_CONSENT_REQUIRED",
            "consent_attested must be true before an OPD packet is stored.",
            400,
        )
    if payload.consent is not None and payload.consent.purpose not in INGEST_PURPOSES:
        raise consent_required_error(
            f"Inline consent purpose '{payload.consent.purpose}' does not cover storing visit "
            "records. Use prior_auth_evidence or continuity_of_care."
        )

    existing = _find_encounter(session, payload.encounter_id, org_id=org_id)
    if existing is not None:
        return existing

    now = payload.encounter_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    patient, patient_created = _resolve_patient(session, payload, now, org_id=org_id)
    consent = _resolve_ingest_consent(
        session,
        payload,
        patient,
        patient_created=patient_created,
        phi_mode=phi_mode,
        org_id=org_id,
        actor=actor or "OpdIngest",
    )
    ingest_id = str(uuid4())
    document_ids: list[str] = []

    note_text = _note_content(payload)
    note_doc = _add_document(
        session,
        patient=patient,
        document_type="clinical_note",
        source=payload.source,
        content=note_text,
        metadata={
            **_base_metadata(payload, ingest_id, role="clinical_note"),
            "consent_id": consent.consent_code,
        },
        now=now,
    )
    document_ids.append(note_doc.document_code)
    session.add(
        ClinicalNote(
            id=str(uuid4()),
            note_code=next_public_code(session, ClinicalNote.note_code, "NOTE"),
            patient_id=patient.id,
            document_id=note_doc.id,
            note_type="opd_encounter",
            content=note_doc.content,
            authored_at=now,
            created_at=now,
            updated_at=now,
        )
    )

    for lab in payload.labs:
        collected = lab.collected_at or now
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=UTC)
        lab_content = f"{lab.test_name}: {lab.value} {lab.unit}".strip()
        if lab.loinc_code:
            lab_content = f"{lab_content} (LOINC {lab.loinc_code})"
        lab_doc = _add_document(
            session,
            patient=patient,
            document_type="lab_result",
            source=payload.source,
            content=lab_content,
            metadata=_base_metadata(
                payload,
                ingest_id,
                role="lab_result",
                test_name=lab.test_name,
                loinc_code=lab.loinc_code or None,
            ),
            now=collected,
        )
        document_ids.append(lab_doc.document_code)
        session.add(
            LabResult(
                id=str(uuid4()),
                lab_code=next_public_code(session, LabResult.lab_code, "LAB"),
                patient_id=patient.id,
                document_id=lab_doc.id,
                test_name=lab.test_name[:120],
                value=lab.value[:64],
                unit=lab.unit[:64],
                collected_at=collected,
                created_at=now,
                updated_at=now,
            )
        )

    for med in payload.medications:
        dose_parts = [med.dose]
        if med.frequency:
            dose_parts.append(med.frequency)
        if med.route:
            dose_parts.append(med.route)
        session.add(
            Medication(
                id=str(uuid4()),
                medication_code=next_public_code(session, Medication.medication_code, "MED"),
                patient_id=patient.id,
                name=med.name[:120],
                dose="; ".join(part for part in dose_parts if part)[:120],
                status=med.status,
                started_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    session.add(
        Procedure(
            id=str(uuid4()),
            procedure_code=next_public_code(session, Procedure.procedure_code, "PROC"),
            patient_id=patient.id,
            name=payload.procedure[:200],
            performed_at=now,
            created_at=now,
            updated_at=now,
        )
    )

    case_code: str | None = None
    if payload.policy_id:
        policy = get_policy_by_code(session, payload.policy_id)
        if policy is None:
            raise NotFoundError("POLICY_NOT_FOUND", "Policy was not found.")
        case = session.scalar(
            select(AuthorizationCase).where(
                AuthorizationCase.patient_id == patient.id,
                AuthorizationCase.policy_id == policy.id,
            )
        )
        if case is None:
            case = AuthorizationCase(
                id=str(uuid4()),
                case_code=next_public_code(session, AuthorizationCase.case_code, "PA"),
                patient_id=patient.id,
                policy_id=policy.id,
                procedure=payload.procedure[:200],
                status="queued",
                created_at=now,
                updated_at=now,
                org_id=getattr(patient, "org_id", None),
            )
            session.add(case)
        else:
            case.procedure = payload.procedure[:200]
            case.updated_at = now
            # New documentation after a closed draft — reopen for re-check, not a new PA case.
            if getattr(case, "status", "") == "closed_as_draft":
                case.status = "queued"
                case.lifecycle_note = "New encounter attached — re-check readiness"
        session.flush()
        case_code = case.case_code
        meta = dict(note_doc.document_metadata or {})
        meta["case_id"] = case_code
        note_doc.document_metadata = meta

    session.flush()
    record_audit(
        session,
        action="opd_ingest",
        actor="OpdIngest",
        resource_type="patient",
        resource_id=patient.patient_code,
        status="created",
        detail=(
            f"ingest={ingest_id};encounter={payload.encounter_id};"
            f"external={payload.external_patient_id};docs={len(document_ids)};"
            f"case={case_code or '-'};source={payload.source};synthetic=true;"
            f"consent={consent.consent_code}"
        ),
    )
    return OpdIngestResponse(
        ingest_id=ingest_id,
        patient_id=patient.patient_code,
        encounter_id=payload.encounter_id,
        external_patient_id=payload.external_patient_id,
        document_ids=document_ids,
        case_id=case_code,
        created=True,
        source=payload.source,
        consent_id=consent.consent_code,
        disclaimer=DISCLAIMER,
    )


def _resolve_ingest_consent(
    session: Session,
    payload: OpdIngestRequest,
    patient: Patient,
    *,
    patient_created: bool,
    phi_mode: bool,
    org_id: str | None,
    actor: str,
) -> ConsentRecord:
    """Return the consent row that authorises storing this packet (creating it when allowed)."""
    if payload.consent_id:
        return require_ingest_consent(session, patient, payload.consent_id, org_id=org_id)
    if payload.consent is not None:
        if phi_mode and not patient_created:
            raise consent_required_error(
                f"Patient {patient.patient_code} already has a chart. Record consent via "
                f"POST /api/v1/patients/{patient.patient_code}/consents and send its consent_id; "
                "inline consent is only accepted when this ingest registers a new patient."
            )
        return record_consent(
            session,
            patient,
            payload.consent,
            recorded_by=actor,
            org_id=org_id,
            via="opd_ingest_inline",
        )
    # Practice / synthetic desk: checkbox attestation stored as a consent row.
    return ensure_practice_consent(session, patient, recorded_by=actor, org_id=org_id)


def _resolve_patient(
    session: Session,
    payload: OpdIngestRequest,
    now: datetime,
    *,
    org_id: str | None = None,
) -> tuple[Patient, bool]:
    org = None
    if org_id:
        from app.models import Organization

        org = session.get(Organization, org_id)
    if org is None:
        org = ensure_default_organization(session)

    if payload.patient_id:
        patient = get_patient_by_code(session, payload.patient_id)
        if patient is None:
            raise NotFoundError("PATIENT_NOT_FOUND", "Patient was not found.")
        _merge_conditions(patient, payload)
        if getattr(patient, "org_id", None) is None:
            patient.org_id = org.id
        patient.updated_at = now
        return patient, False
    existing = _find_patient_by_external(
        session, payload.external_patient_id, org_id=org.id
    )
    if existing is None and not org_id:
        # Org scope off: a legacy chart created before org stamping (org_id null)
        # is still the same facility's patient. Never consulted when an org is bound.
        existing = _find_patient_by_external(
            session, payload.external_patient_id, org_id=None
        )
    if existing is not None:
        _merge_conditions(existing, payload)
        if getattr(existing, "org_id", None) is None:
            existing.org_id = org.id
        existing.updated_at = now
        return existing, False
    birth = payload.birth_date or date(2000, 1, 1)
    display = payload.display_name.strip() or f"OPD Patient {payload.external_patient_id}"
    patient = Patient(
        id=str(uuid4()),
        patient_code=next_public_code(session, Patient.patient_code, "PAT"),
        synthetic_name=display[:120],
        birth_date=birth,
        sex=payload.sex[:16],
        conditions=_unique_conditions([item.display for item in payload.diagnoses]),
        created_at=now,
        updated_at=now,
        org_id=org.id,
    )
    session.add(patient)
    session.flush()
    return patient, True


def _merge_conditions(patient: Patient, payload: OpdIngestRequest) -> None:
    incoming = [item.display for item in payload.diagnoses if item.display.strip()]
    if not incoming:
        return
    patient.conditions = _unique_conditions([*(patient.conditions or []), *incoming])


def _unique_conditions(values: list[str], *, limit: int = 40) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        text = " ".join(str(raw).split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:200])
        if len(out) >= limit:
            break
    return out


def _find_patient_by_external(
    session: Session,
    external_patient_id: str,
    *,
    org_id: str | None = None,
) -> Patient | None:
    for document in _opd_documents(session):
        meta = document.document_metadata or {}
        if meta.get("external_patient_id") != external_patient_id:
            continue
        if not document.patient_id:
            continue
        patient = session.get(Patient, document.patient_id)
        if patient is None:
            continue
        if not _same_org(getattr(patient, "org_id", None), org_id):
            continue
        return patient
    return None


def _same_org(patient_org: str | None, org_id: str | None) -> bool:
    """MRNs are only unique inside one facility — never merge charts across orgs.

    With an org bound, match only charts stamped to that org. Without one (org scope
    off / legacy rows), match only charts that are also unbound.
    """
    if org_id:
        return patient_org == org_id
    return not patient_org


def _find_encounter(
    session: Session,
    encounter_id: str,
    *,
    org_id: str | None = None,
) -> OpdIngestResponse | None:
    note_doc: Document | None = None
    document_ids: list[str] = []
    ingest_id = ""
    external_patient_id = ""
    patient_id = ""
    for document in _opd_documents(session):
        meta = document.document_metadata or {}
        if meta.get("encounter_id") != encounter_id:
            continue
        if not document.patient_id:
            continue
        patient = session.get(Patient, document.patient_id)
        if patient is None:
            continue
        if org_id and getattr(patient, "org_id", None) != org_id:
            continue
        document_ids.append(document.document_code)
        ingest_id = str(meta.get("ingest_id") or ingest_id)
        external_patient_id = str(meta.get("external_patient_id") or external_patient_id)
        if meta.get("role") == "clinical_note":
            note_doc = document
            patient_id = patient.patient_code
    if note_doc is None or not patient_id:
        return None
    meta = note_doc.document_metadata or {}
    case_code = str(meta["case_id"]) if meta.get("case_id") else None
    return OpdIngestResponse(
        ingest_id=ingest_id or str(uuid4()),
        patient_id=patient_id,
        encounter_id=encounter_id,
        external_patient_id=external_patient_id,
        document_ids=document_ids,
        case_id=case_code,
        created=False,
        source=str(meta.get("source") or "opd_manual"),
        consent_id=str(meta["consent_id"]) if meta.get("consent_id") else None,
        disclaimer=DISCLAIMER,
    )


def _opd_documents(session: Session) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .where(Document.source.in_(tuple(_OPD_SOURCES)))
            .order_by(Document.created_at)
        ).all()
    )


def _specialty_from_payload(payload: OpdIngestRequest) -> str:
    from app.services.specialties import normalize_specialty

    return normalize_specialty(payload.department)


def _base_metadata(
    payload: OpdIngestRequest,
    ingest_id: str,
    *,
    role: str,
    test_name: str | None = None,
    loinc_code: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ingest_id": ingest_id,
        "encounter_id": payload.encounter_id,
        "external_patient_id": payload.external_patient_id,
        "role": role,
        "source": payload.source,
        "facility_name": payload.facility_name,
        "department": payload.department,
        "specialty": _specialty_from_payload(payload),
        "visit_type": payload.visit_type,
        "synthetic": True,
        "consent_attested": True,
        "embedding_method": EMBEDDING_METHOD,
        "dataset": "opd_hospital_compatible",
    }
    if test_name:
        meta["test_name"] = test_name
    if loinc_code:
        meta["loinc_code"] = loinc_code
    return meta


def _note_content(payload: OpdIngestRequest) -> str:
    lines = [
        f"OPD_ENCOUNTER_{payload.encounter_id}.",
        f"MRN/UHID: {payload.external_patient_id}.",
        f"Visit type: {payload.visit_type}. Department: {payload.department or 'OPD'}.",
    ]
    if payload.facility_name:
        lines.append(f"Facility: {payload.facility_name}.")
    if payload.attending_provider:
        lines.append(f"Attending: {payload.attending_provider}.")
    lines.append(f"Source: {payload.source}. Synthetic OPD packet. {PROTOTYPE_BANNER}")
    if payload.chief_complaint:
        lines.append("Chief complaint:")
        lines.append(payload.chief_complaint.strip())
    if payload.history_of_present_illness:
        lines.append("History of present illness:")
        lines.append(payload.history_of_present_illness.strip())
    if payload.diagnoses:
        lines.append("Diagnoses:")
        for dx in payload.diagnoses:
            code = f"{dx.code_system} {dx.code}".strip() if dx.code else dx.code_system
            label = f"{dx.display}" + (f" ({code})" if code else "")
            lines.append(f"- {label}")
    if payload.vitals:
        lines.append("Vitals:")
        for vital in payload.vitals:
            lines.append(f"- {vital.name}: {vital.value} {vital.unit}".strip())
    if payload.assessment_and_plan:
        lines.append("Assessment and plan:")
        lines.append(payload.assessment_and_plan.strip())
    if payload.note.strip():
        lines.append("Visit note:")
        lines.append(payload.note.strip())
    if payload.medications:
        lines.append("Medications:")
        for med in payload.medications:
            detail = med.name
            if med.dose:
                detail += f" · {med.dose}"
            if med.frequency:
                detail += f" · {med.frequency}"
            if med.route:
                detail += f" · {med.route}"
            lines.append(f"- {detail} ({med.status})")
    return "\n".join(lines)


def _add_document(
    session: Session,
    *,
    patient: Patient,
    document_type: str,
    source: str,
    content: str,
    metadata: dict[str, Any],
    now: datetime,
) -> Document:
    document = Document(
        id=str(uuid4()),
        document_code=next_public_code(session, Document.document_code, "DOC"),
        patient_id=patient.id,
        document_type=document_type,
        source=source,
        content=content.strip(),
        document_metadata=metadata,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.flush()
    index_document(session, document)
    return document
