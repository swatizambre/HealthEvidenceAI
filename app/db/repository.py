"""Database query helpers for the evidence store."""

from __future__ import annotations

import re

from sqlalchemy import func, select, text
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
    """Allocate the next zero-padded public code (serialized per prefix on PostgreSQL)."""
    if _dialect_name(session) == "postgresql":
        # Transaction-scoped advisory lock keyed on the prefix: concurrent allocators for
        # the same prefix (e.g. two OPD ingests minting NOTE-xxxxxx) queue here until the
        # holder commits, so they never read the same max. Unlike FOR SHARE on the whole
        # column, it does not lock table rows and different prefixes do not contend.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:prefix))"), {"prefix": prefix})
    # SQLite serializes writers at the database level; a plain read is sufficient there.
    values = list(session.scalars(select(column).where(column.like(f"{prefix}-%"))).all())
    # Pending inserts in this transaction are invisible to SELECT until flush — include them
    # so multi-row OPD packs (several labs/meds) do not reuse the same code.
    attr_name = column.key
    for obj in session.new:
        pending = getattr(obj, attr_name, None)
        if isinstance(pending, str):
            values.append(pending)
    highest = 0
    for value in values:
        if not isinstance(value, str):
            continue
        match = _CODE.fullmatch(value)
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)))
    # max + 1 is never taken, and always matches the PREFIX-NNNNNN schema patterns.
    return f"{prefix}-{highest + 1:06d}"


def _dialect_name(session: Session) -> str:
    try:
        return str(session.get_bind().dialect.name)
    except Exception:  # noqa: BLE001 — unbound session: treat as generic dialect
        return ""


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
