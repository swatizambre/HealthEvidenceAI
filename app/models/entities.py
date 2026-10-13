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
