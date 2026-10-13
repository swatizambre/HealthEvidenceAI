"""Assemble citeable patient records from stored documents and chunks."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repository import (
    chunks_by_document,
    get_documents_by_ids,
    list_labs,
    list_notes,
)
from app.models import Patient
from app.services.evaluator import LabRecord, TextRecord


@dataclass(frozen=True)
class PatientRecords:
    notes: list[TextRecord]
    labs: list[LabRecord]


def load_patient_records(session: Session, patient: Patient) -> PatientRecords:
    notes = list_notes(session, patient.id)
    labs = list_labs(session, patient.id)
    document_ids = [note.document_id for note in notes] + [lab.document_id for lab in labs]
    documents = get_documents_by_ids(session, document_ids)
    grouped = chunks_by_document(session, list(documents))
    note_records: list[TextRecord] = []
    for note in notes:
        document = documents.get(note.document_id)
        if document is None:
            continue
        chunks = tuple((chunk.chunk_code, chunk.content) for chunk in grouped.get(document.id, []))
        if not chunks:
            continue
        note_records.append(
            TextRecord(
                content=document.content,
                document_id=document.document_code,
                chunks=chunks,
                source="clinical_note",
            )
        )
    lab_records: list[LabRecord] = []
    for lab in labs:
        document = documents.get(lab.document_id)
        if document is None:
            continue
        chunks = tuple((chunk.chunk_code, chunk.content) for chunk in grouped.get(document.id, []))
        if not chunks:
            continue
        lab_records.append(
            LabRecord(
                test_name=lab.test_name,
                content=document.content,
                document_id=document.document_code,
                chunks=chunks,
                value=str(lab.value or ""),
                unit=str(lab.unit or ""),
                collected_at=lab.collected_at,
            )
        )
    return PatientRecords(notes=note_records, labs=lab_records)
