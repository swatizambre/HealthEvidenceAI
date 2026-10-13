"""Patient rights: accounting of access, data export, and data-subject requests.

Maps to DPDP Act 2023 s.11 (access summary), s.12 (correction / erasure), s.13 (grievance),
s.14 (nominee), and HIPAA 45 CFR 164.524 (access) / 164.526 (amendment) / 164.528 (accounting).

Erasure is a *request workflow only*: clinical records are kept for statutory retention
periods (e.g. Indian Medical Council regulations, state clinical-establishment rules, HIPAA
state-law retention), so resolution must record either the legal-hold reason or completion.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.core.safety import DISCLAIMER
from app.db.repository import (
    list_documents_for_patient,
    list_imaging,
    list_labs,
    list_medications,
    list_notes,
    list_procedures,
    next_public_code,
)
from app.models import AuditEvent, DataSubjectRequest, Patient
from app.schemas.api import (
    AccessLogEntryOut,
    AccessLogResponse,
    DataSubjectRequestCreate,
    DataSubjectRequestListResponse,
    DataSubjectRequestOut,
    DataSubjectRequestResolve,
    Demographics,
    ExportDocumentOut,
    ImagingOut,
    LabOut,
    MedicationOut,
    NoteOut,
    PatientExportResponse,
    ProcedureOut,
)
from app.services.audit import record_audit
from app.services.consent import consent_out, list_consents_for_patient, mask_staff_subject
from app.services.pseudonym import staff_reference

_PATIENT_CODE = re.compile(r"^PAT-\d{6}$")

ActorCategory = Literal[
    "you", "care_team", "care_team_emergency", "system", "other_patient", "unknown"
]

# Service actors written by the platform itself (not a person).
SYSTEM_ACTORS = frozenset(
    {
        "OpdIngest",
        "AuthorizationAgent",
        "Orchestrator",
        "hospital-interface",
        "care-team",
        "ClinicalEvidenceAgent",
        "PolicyAgent",
        "system",
        "unknown",
    }
)

ACTION_LABELS: dict[str, str] = {
    "chart_read": "Opened your chart",
    "chart_access": "Opened your chart",
    "essentials_read": "Viewed your chart summary",
    "timeline_read": "Viewed your timeline",
    "lifelong_read": "Viewed your lifelong record",
    "documents_list": "Listed your documents",
    "document_read": "Read one of your documents",
    "evidence_search": "Searched your record for evidence",
    "evidence_graph": "Viewed your evidence graph",
    "authorization_review": "Ran an insurance evidence review",
    "evidence_pack_prepare": "Prepared an insurance evidence pack",
    "pack_export": "Exported an insurance evidence pack",
    "opd_ingest": "Added a visit record",
    "patient_scope_denied": "Tried to open your chart (blocked)",
    "break_glass": "Emergency (break-glass) access opened",
    "consent_recorded": "Recorded a consent",
    "consent_revoked": "Withdrew a consent",
    "consent_list": "Viewed your consents",
    "consent_manage": "Opened your consent records",
    "data_export": "Downloaded a copy of your data",
    "access_log_read": "Viewed this access history",
    "dsr_created": "Submitted a privacy request",
    "dsr_list": "Viewed privacy requests",
    "dsr_review": "Reviewed a privacy request",
    "dsr_updated": "Updated a privacy request",
}

REQUEST_TYPES: tuple[str, ...] = ("correction", "erasure", "grievance", "nominee")
_CLOSED = frozenset({"resolved", "rejected"})
_MIN_RESOLUTION_NOTE = 10


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def classify_actor(actor: str, patient_code: str, detail: str) -> tuple[ActorCategory, str]:
    """Return (category, safe display label) without leaking staff personal identifiers."""
    raw = (actor or "").strip()
    if not raw:
        return "unknown", "Unknown"
    # Self-scope audits carry detail "self" even when the IdP subject is not the PAT code.
    if raw.upper() == patient_code or (detail or "").split(";", 1)[0] == "self":
        return "you", "You"
    if _PATIENT_CODE.fullmatch(raw.upper()):
        return "other_patient", "Another patient account"
    if raw in SYSTEM_ACTORS:
        return "system", f"System ({raw})"
    ref = staff_reference(raw)
    if "break_glass" in (detail or ""):
        return "care_team_emergency", f"Care team member (emergency access) · ref {ref}"
    return "care_team", f"Care team member · ref {ref}"


def action_label(action: str) -> str:
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    if action.startswith("mcp_tool_") or action.startswith("mcp_"):
        return "An AI assistant tool read your record"
    return action.replace("_", " ").strip().capitalize() or "Activity"


def _access_filter(patient_code: str) -> ColumnElement[bool]:
    # detail is "k=v;k=v" — match the exact code (followed by ';' or end of string).
    return or_(
        and_(AuditEvent.resource_type == "patient", AuditEvent.resource_id == patient_code),
        AuditEvent.detail.like(f"%patient={patient_code};%"),
        AuditEvent.detail.like(f"%patient={patient_code}"),
    )


def access_log(
    session: Session,
    patient_code: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> AccessLogResponse:
    """Newest-first accounting of who touched this patient's record."""
    clause = _access_filter(patient_code)
    total = int(
        session.scalar(select(func.count()).select_from(AuditEvent).where(clause)) or 0
    )
    bounded = min(max(limit, 1), 200)
    rows = session.scalars(
        select(AuditEvent)
        .where(clause)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(max(offset, 0))
        .limit(bounded)
    ).all()
    entries: list[AccessLogEntryOut] = []
    for row in rows:
        category, label = classify_actor(row.actor, patient_code, row.detail)
        entries.append(
            AccessLogEntryOut(
                event_id=row.id,
                occurred_at=_as_utc(row.created_at) or datetime.now(UTC),
                actor_label=label,
                actor_category=category,
                action=row.action,
                action_label=action_label(row.action),
                outcome="denied" if row.status in {"denied", "forbidden"} else "allowed",
            )
        )
    return AccessLogResponse(
        patient_id=patient_code,
        total=total,
        limit=bounded,
        offset=max(offset, 0),
        entries=entries,
        disclaimer=(
            "Staff are shown by role and a pseudonymous reference. Ask the facility grievance "
            "officer to identify a specific access."
        ),
    )


def dsr_out(
    row: DataSubjectRequest, patient_code: str, *, mask_staff: bool = False
) -> DataSubjectRequestOut:
    handled = row.handled_by
    if mask_staff and handled:
        handled = mask_staff_subject(handled)
    return DataSubjectRequestOut(
        request_id=row.request_code,
        patient_id=patient_code,
        request_type=row.request_type,
        details=row.details or "",
        status=row.status,
        created_at=_as_utc(row.created_at) or datetime.now(UTC),
        resolved_at=_as_utc(row.resolved_at),
        resolution_note=row.resolution_note or "",
        outcome=row.outcome or "",
        handled_by=handled,
    )


def create_request(
    session: Session,
    patient: Patient,
    payload: DataSubjectRequestCreate,
    *,
    submitted_by: str,
) -> DataSubjectRequest:
    now = datetime.now(UTC)
    row = DataSubjectRequest(
        id=str(uuid4()),
        request_code=next_public_code(session, DataSubjectRequest.request_code, "DSR"),
        patient_id=patient.id,
        org_id=getattr(patient, "org_id", None),
        request_type=payload.request_type,
        details=payload.details,
        status="open",
        submitted_by=(submitted_by or "")[:120],
        created_at=now,
        resolved_at=None,
        resolution_note="",
        outcome="",
        handled_by=None,
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        action="dsr_created",
        actor=(submitted_by or "unknown")[:64],
        resource_type="data_subject_request",
        resource_id=row.request_code,
        status="created",
        detail=f"patient={patient.patient_code};type={row.request_type}",
    )
    return row


def list_requests_for_patient(
    session: Session, patient: Patient, *, mask_staff: bool = False
) -> DataSubjectRequestListResponse:
    rows = list(
        session.scalars(
            select(DataSubjectRequest)
            .where(DataSubjectRequest.patient_id == patient.id)
            .order_by(DataSubjectRequest.created_at.desc(), DataSubjectRequest.request_code.desc())
        ).all()
    )
    return DataSubjectRequestListResponse(
        total=len(rows),
        requests=[dsr_out(row, patient.patient_code, mask_staff=mask_staff) for row in rows],
    )


def list_requests_for_org(
    session: Session,
    *,
    org_id: str | None,
    status: str | None = None,
    request_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> DataSubjectRequestListResponse:
    filters: list[ColumnElement[bool]] = []
    if org_id:
        filters.append(Patient.org_id == org_id)
    if status:
        filters.append(DataSubjectRequest.status == status)
    if request_type:
        filters.append(DataSubjectRequest.request_type == request_type)
    base = select(DataSubjectRequest, Patient.patient_code).join(
        Patient, DataSubjectRequest.patient_id == Patient.id
    )
    count_stmt = (
        select(func.count())
        .select_from(DataSubjectRequest)
        .join(Patient, DataSubjectRequest.patient_id == Patient.id)
    )
    if filters:
        base = base.where(*filters)
        count_stmt = count_stmt.where(*filters)
    total = int(session.scalar(count_stmt) or 0)
    rows = session.execute(
        base.order_by(DataSubjectRequest.created_at.desc(), DataSubjectRequest.request_code.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
    ).all()
    return DataSubjectRequestListResponse(
        total=total,
        requests=[dsr_out(row[0], str(row[1])) for row in rows],
    )


def get_request_by_code(session: Session, request_code: str) -> DataSubjectRequest | None:
    return session.scalar(
        select(DataSubjectRequest).where(
            DataSubjectRequest.request_code == request_code.strip().upper()
        )
    )


def resolve_request(
    session: Session,
    row: DataSubjectRequest,
    patient: Patient,
    payload: DataSubjectRequestResolve,
    *,
    handled_by: str,
) -> DataSubjectRequest:
    """Move a request through in_review → resolved/rejected with a documented outcome."""
    if row.status in _CLOSED:
        raise AppError("DSR_CLOSED", "This request is already closed.", 409)
    note = payload.resolution_note.strip()
    closing = payload.status in _CLOSED
    if closing and len(note) < _MIN_RESOLUTION_NOTE:
        raise AppError(
            "DSR_RESOLUTION_NOTE_REQUIRED",
            "Closing a request requires a resolution note explaining the outcome.",
            422,
        )
    if row.request_type == "erasure" and closing and payload.outcome is None:
        raise AppError(
            "DSR_ERASURE_OUTCOME_REQUIRED",
            "Erasure requests must state an outcome: retained_legal_hold (medical-record "
            "retention law applies), restricted_processing, or completed_outside_system.",
            422,
        )
    row.status = payload.status
    if note:
        row.resolution_note = note
    if payload.outcome is not None:
        row.outcome = payload.outcome
    row.handled_by = (handled_by or "unknown")[:120]
    if closing:
        row.resolved_at = datetime.now(UTC)
    session.flush()
    record_audit(
        session,
        action="dsr_updated",
        actor=(handled_by or "unknown")[:64],
        resource_type="data_subject_request",
        resource_id=row.request_code,
        status=row.status,
        detail=(
            f"patient={patient.patient_code};type={row.request_type};"
            f"outcome={row.outcome or '-'}"
        ),
    )
    return row


def require_request_patient(session: Session, row: DataSubjectRequest) -> Patient:
    patient = session.get(Patient, row.patient_id)
    if patient is None:
        raise NotFoundError("DSR_NOT_FOUND", "Request was not found.")
    return patient


def build_export(session: Session, patient: Patient) -> PatientExportResponse:
    """Machine-readable copy of the patient's own record (right of access / portability)."""
    from app.services.lifelong import get_lifelong_summary

    documents = list_documents_for_patient(session, patient.id)
    doc_codes = {doc.id: doc.document_code for doc in documents}
    lifelong = get_lifelong_summary(session, patient.patient_code)
    consents = list_consents_for_patient(session, patient.id)
    return PatientExportResponse(
        generated_at=datetime.now(UTC),
        patient_id=patient.patient_code,
        demographics=Demographics(
            patient_id=patient.patient_code,
            synthetic_name=patient.synthetic_name,
            date_of_birth=patient.birth_date,
            sex=patient.sex,
        ),
        conditions=[str(item) for item in (patient.conditions or [])],
        documents=[
            ExportDocumentOut(
                document_id=doc.document_code,
                document_type=doc.document_type,
                source=doc.source,
                created_at=_as_utc(doc.created_at) or datetime.now(UTC),
                content=doc.content,
            )
            for doc in documents
        ],
        clinical_notes=[
            NoteOut(
                note_id=note.note_code,
                note_type=note.note_type,
                content=note.content,
                authored_at=_as_utc(note.authored_at) or datetime.now(UTC),
                document_id=doc_codes.get(note.document_id, ""),
            )
            for note in list_notes(session, patient.id)
        ],
        labs=[
            LabOut(
                lab_id=lab.lab_code,
                test_name=lab.test_name,
                value=lab.value,
                unit=lab.unit,
                collected_at=_as_utc(lab.collected_at) or datetime.now(UTC),
            )
            for lab in list_labs(session, patient.id)
        ],
        medications=[
            MedicationOut(
                medication_id=med.medication_code,
                name=med.name,
                dose=med.dose,
                status=med.status,
                started_at=_as_utc(med.started_at) or datetime.now(UTC),
            )
            for med in list_medications(session, patient.id)
        ],
        procedures=[
            ProcedureOut(
                procedure_id=proc.procedure_code,
                name=proc.name,
                performed_at=_as_utc(proc.performed_at) or datetime.now(UTC),
            )
            for proc in list_procedures(session, patient.id)
        ],
        imaging=[
            ImagingOut(
                imaging_id=img.imaging_code,
                modality=img.modality,
                body_part=img.body_part,
                study_date=_as_utc(img.studied_at) or datetime.now(UTC),
                description=img.description,
            )
            for img in list_imaging(session, patient.id)
        ],
        consents=[consent_out(row, patient.patient_code, mask_staff=True) for row in consents],
        requests=list_requests_for_patient(session, patient, mask_staff=True).requests,
        lifelong_events=list(lifelong.events),
        disclaimer=DISCLAIMER,
    )
