"""Database query helpers for the evidence store."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import (
    AuthorizationCase,
    Claim,
    ClinicalNote,
    Document,
    DocumentChunk,
    ImagingStudy,
    InsurancePolicy,
    LabResult,
    Medication,
    Patient,
    PolicyCriterion,
    Procedure,
)

_CODE = re.compile(r"^([A-Z]+)-(\d+)$")


def next_public_code(session: Session, column: InstrumentedAttribute[str], prefix: str) -> str:
    """Allocate the next zero-padded public code (collision-resistant under concurrency)."""
    import secrets

    # Prefer a locked max read when the dialect supports it (Postgres).
    try:
        statement = select(column).execution_options(populate_existing=True)
        values = list(session.scalars(statement.with_for_update(read=True)).all())
    except Exception:  # noqa: BLE001 — SQLite / dialects without FOR UPDATE
        values = list(session.scalars(select(column)).all())
    highest = 0
    existing = set()
    for value in values:
        if not isinstance(value, str):
            continue
        existing.add(value)
        match = _CODE.fullmatch(value)
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)))
    for offset in range(0, 64):
        candidate = f"{prefix}-{highest + 1 + offset:06d}"
        if candidate not in existing:
            return candidate
    # Extremely unlikely fallback — still unique within the prefix namespace.
    return f"{prefix}-{highest + 1:06d}-{secrets.token_hex(3).upper()}"


def count_rows(session: Session, model: type[object]) -> int:
    total = session.scalar(select(func.count()).select_from(model))
    return int(total or 0)


def list_patients(
    session: Session,
    *,
    offset: int,
    limit: int,
    org_id: str | None = None,
) -> list[Patient]:
    statement = select(Patient).order_by(Patient.patient_code)
    if org_id:
        statement = statement.where(Patient.org_id == org_id)
    statement = statement.offset(offset).limit(limit)
    return list(session.scalars(statement).all())


def get_patient_by_code(session: Session, patient_code: str) -> Patient | None:
    return session.scalar(select(Patient).where(Patient.patient_code == patient_code))


def list_notes(session: Session, patient_id: str) -> list[ClinicalNote]:
    statement = (
        select(ClinicalNote)
        .where(ClinicalNote.patient_id == patient_id)
        .order_by(ClinicalNote.authored_at, ClinicalNote.note_code)
    )
    return list(session.scalars(statement).all())


def list_labs(session: Session, patient_id: str) -> list[LabResult]:
    statement = (
        select(LabResult)
        .where(LabResult.patient_id == patient_id)
        .order_by(LabResult.collected_at, LabResult.lab_code)
    )
    return list(session.scalars(statement).all())


def list_medications(session: Session, patient_id: str) -> list[Medication]:
    statement = (
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .order_by(Medication.medication_code)
    )
    return list(session.scalars(statement).all())


def list_procedures(session: Session, patient_id: str) -> list[Procedure]:
    statement = (
        select(Procedure)
        .where(Procedure.patient_id == patient_id)
        .order_by(Procedure.performed_at, Procedure.procedure_code)
    )
    return list(session.scalars(statement).all())


def list_imaging(session: Session, patient_id: str) -> list[ImagingStudy]:
    statement = (
        select(ImagingStudy)
        .where(ImagingStudy.patient_id == patient_id)
        .order_by(ImagingStudy.studied_at, ImagingStudy.imaging_code)
    )
    return list(session.scalars(statement).all())


def list_claims(session: Session, patient_id: str) -> list[Claim]:
    statement = (
        select(Claim)
        .where(Claim.patient_id == patient_id)
        .order_by(Claim.service_date, Claim.claim_code)
    )
    return list(session.scalars(statement).all())


def list_policies(session: Session) -> list[InsurancePolicy]:
    return list(
        session.scalars(select(InsurancePolicy).order_by(InsurancePolicy.policy_code)).all()
    )


def get_policy_by_code(session: Session, policy_code: str) -> InsurancePolicy | None:
    return session.scalar(select(InsurancePolicy).where(InsurancePolicy.policy_code == policy_code))


def list_criteria(session: Session, policy_id: str) -> list[PolicyCriterion]:
    statement = (
        select(PolicyCriterion)
        .where(PolicyCriterion.policy_id == policy_id)
        .order_by(PolicyCriterion.position, PolicyCriterion.criterion_code)
    )
    return list(session.scalars(statement).all())


def get_case_by_code(session: Session, case_code: str) -> AuthorizationCase | None:
    return session.scalar(select(AuthorizationCase).where(AuthorizationCase.case_code == case_code))


def list_cases(
    session: Session,
    *,
    org_id: str | None = None,
) -> list[tuple[AuthorizationCase, str, str, str]]:
    statement = (
        select(
            AuthorizationCase,
            Patient.patient_code,
            InsurancePolicy.policy_code,
            InsurancePolicy.title,
        )
        .join(Patient, AuthorizationCase.patient_id == Patient.id)
        .join(InsurancePolicy, AuthorizationCase.policy_id == InsurancePolicy.id)
        .order_by(AuthorizationCase.case_code)
    )
    if org_id:
        statement = statement.where(Patient.org_id == org_id)
    rows = session.execute(statement).all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


def get_document_by_code(session: Session, document_code: str) -> Document | None:
    return session.scalar(select(Document).where(Document.document_code == document_code))


def list_documents_for_patient(session: Session, patient_id: str) -> list[Document]:
    statement = (
        select(Document).where(Document.patient_id == patient_id).order_by(Document.document_code)
    )
    return list(session.scalars(statement).all())


def get_documents_by_ids(session: Session, document_ids: list[str]) -> dict[str, Document]:
    if not document_ids:
        return {}
    rows = session.scalars(select(Document).where(Document.id.in_(document_ids))).all()
    return {row.id: row for row in rows}


def chunks_by_document(session: Session, document_ids: list[str]) -> dict[str, list[DocumentChunk]]:
    if not document_ids:
        return {}
    rows = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids))
    ).all()
    grouped: dict[str, list[DocumentChunk]] = {}
    for row in rows:
        grouped.setdefault(row.document_id, []).append(row)
    for group in grouped.values():
        group.sort(key=lambda chunk: chunk.chunk_index)
    return grouped


def count_chunks(session: Session, document_id: str) -> int:
    total = session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
    )
    return int(total or 0)
