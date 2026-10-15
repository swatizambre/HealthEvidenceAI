"""Relational entities for synthetic patients, documents, and policies."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class IdentityMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        nullable=False,
    )


class Organization(IdentityMixin, TimestampMixin, Base):
    """Tenant / facility org for multi-hospital continuity (stub for enterprise)."""

    __tablename__ = "organizations"

    org_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    facility_type: Mapped[str] = mapped_column(String(64), default="multispecialty")
    active: Mapped[bool] = mapped_column(default=True)


class Patient(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "patients"

    patient_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    synthetic_name: Mapped[str] = mapped_column(String(120))
    birth_date: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(16))
    conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ABDM sandbox stub — never treat as a live HIU link until certified.
    abha_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Document(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    document_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str | None] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    document_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class DocumentFile(IdentityMixin, TimestampMixin, Base):
    """Original uploaded report binary (PDF/image) for in-app preview."""

    __tablename__ = "document_files"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(260), default="")
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(500))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")


class DocumentChunk(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    chunk_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ClinicalNote(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "clinical_notes"

    note_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    note_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    authored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LabResult(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "lab_results"

    lab_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    test_name: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(64))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Medication(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "medications"

    medication_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    dose: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Procedure(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "procedures"

    procedure_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImagingStudy(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "imaging_studies"

    imaging_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    modality: Mapped[str] = mapped_column(String(32))
    body_part: Mapped[str] = mapped_column(String(64))
    studied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text)


class Claim(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "claims"

    claim_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32))
    amount_cents: Mapped[int] = mapped_column(Integer)
    service_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InsurancePolicy(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "insurance_policies"

    policy_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    payer_name: Mapped[str] = mapped_column(String(120))
    procedure_name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )


class PolicyCriterion(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "policy_criteria"

    criterion_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"),
        index=True,
    )
    description: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    rule: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuthorizationCase(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "authorization_cases"

    case_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"),
        index=True,
    )
    procedure: Mapped[str] = mapped_column(String(200))
    # Decision-support lifecycle only — never approve/deny.
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_note: Mapped[str] = mapped_column(String(500), default="")
    # Packet cycle-time: first prepare → ready for clinician HITL.
    prep_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Clinician/staff subject from JWT — powers Today "my queue".
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # --- India cashless pre-authorization desk (docs/TPA_DESK_CONTRACT.md) ---
    # Nullable / defaulted so pre-desk rows keep working. A case is a "desk case"
    # once payer_type is set. Stage records what the insurer/TPA did; the product
    # itself never approves or denies anything.
    payer_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    insurer_name: Mapped[str] = mapped_column(String(160), default="")
    tpa_name: Mapped[str] = mapped_column(String(160), default="")
    policy_number: Mapped[str] = mapped_column(String(64), default="")
    admission_type: Mapped[str] = mapped_column(String(16), default="planned")
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_discharge_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    treating_doctor: Mapped[str] = mapped_column(String(160), default="")
    provisional_diagnosis: Mapped[str] = mapped_column(String(300), default="")
    icd10_code: Mapped[str] = mapped_column(String(16), default="")
    proposed_treatment: Mapped[str] = mapped_column(String(300), default="")
    estimated_cost_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_amount_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discharge_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    final_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Contract additions (allowed: add, never rename/remove).
    revised_estimate_inr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enhancement_reason: Mapped[str] = mapped_column(String(500), default="")
    enhancement_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enhancement_count: Mapped[int] = mapped_column(Integer, default=0)
    discharge_override_reason: Mapped[str] = mapped_column(String(500), default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cost estimate lines (room, icu, ot, professional_fees, medicines_consumables,
    # investigations, implants) and extra pre-auth form fields (room_type, gpla, mlc_number…).
    cost_breakdown_inr: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    form_extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CaseQuery(IdentityMixin, TimestampMixin, Base):
    """Insurer/TPA query on a cashless case and the hospital's response."""

    __tablename__ = "case_queries"

    query_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("authorization_cases.id", ondelete="CASCADE"), index=True
    )
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str] = mapped_column(Text, default="")
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response: Mapped[str] = mapped_column(Text, default="")
    raised_by: Mapped[str] = mapped_column(String(120), default="")
    responded_by: Mapped[str] = mapped_column(String(120), default="")
    # Stage to return to once every open query is answered (sent / enhancement / discharge_sent).
    resume_stage: Mapped[str] = mapped_column(String(32), default="sent")


class ReviewRun(Base):
    """Durable HITL pause/resume state for authorization review runs."""

    __tablename__ = "review_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class AuditEvent(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "audit_events"

    action: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(500), default="")


class HospitalPipelineRunRow(IdentityMixin, TimestampMixin, Base):
    """Durable hospital HIS/FHIR pipeline run (survives restart / multi-replica)."""

    __tablename__ = "hospital_pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    patient_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    encounter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    readiness_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gap_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_prepared: Mapped[bool] = mapped_column(default=False)
    detail: Mapped[str] = mapped_column(String(500), default="")
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(120), default="")


class ConsentRecord(IdentityMixin, Base):
    """Stored consent artefact (DPDP s.6 / HIPAA authorization trail) for one patient + purpose.

    Rows are never deleted: withdrawal sets ``revoked_at`` so the history of what was
    permitted, when, and on what notice version stays auditable.
    """

    __tablename__ = "consent_records"

    consent_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # prior_auth_evidence | continuity_of_care | research_trial
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    scope: Mapped[str] = mapped_column(Text, default="")
    # written | electronic | verbal_witnessed
    method: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16), default="en")
    notice_version: Mapped[str] = mapped_column(String(64))
    granted_by_name: Mapped[str] = mapped_column(String(120))
    recorded_by: Mapped[str] = mapped_column(String(120))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str] = mapped_column(String(500), default="")
    revoked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence_ref: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class DataSubjectRequest(IdentityMixin, Base):
    """Patient rights request (correction / erasure / grievance / nominee) — workflow only.

    Erasure never hard-deletes clinical rows: medical-record retention law usually
    overrides (see docs/CONSENT_AND_RIGHTS.md). Resolution records the outcome.
    """

    __tablename__ = "data_subject_requests"

    request_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # correction | erasure | grievance | nominee
    request_type: Mapped[str] = mapped_column(String(32), index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    # open | in_review | resolved | rejected
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    submitted_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    # Erasure outcome: retained_legal_hold | restricted_processing | completed_outside_system
    outcome: Mapped[str] = mapped_column(String(40), default="")
    handled_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class EmergencyProfile(IdentityMixin, TimestampMixin, Base):
    """Patient-owned emergency card fields (demo scaffolding)."""

    __tablename__ = "emergency_profiles"

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), unique=True, index=True
    )
    blood_group: Mapped[str] = mapped_column(String(16), default="")
    implants: Mapped[str] = mapped_column(Text, default="")
    emergency_contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    show_on_lock_screen: Mapped[bool] = mapped_column(default=True)


class RecordShare(IdentityMixin, TimestampMixin, Base):
    """Time-limited share link a patient creates for a doctor (demo scaffolding)."""

    __tablename__ = "record_shares"

    share_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(160), default="")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), default="")
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CareRelationship(IdentityMixin, TimestampMixin, Base):
    """Family / caregiver link stub (demo — not full multi-account auth)."""

    __tablename__ = "care_relationships"

    relationship_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    related_display_name: Mapped[str] = mapped_column(String(160))
    # parent | child | spouse | caregiver | other
    relationship_type: Mapped[str] = mapped_column(String(32), default="caregiver")
    related_patient_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_level: Mapped[str] = mapped_column(String(32), default="view")  # view | manage
