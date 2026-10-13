"""Store a document, index it, and link clinical notes to a patient."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.repository import get_patient_by_code, next_public_code
from app.models import ClinicalNote, Document
from app.schemas.api import DocumentCreate, DocumentOut
from app.services.embeddings import EMBEDDING_METHOD
from app.services.indexing import index_document
from app.services.records import get_document_detail


def ingest_document(session: Session, payload: DocumentCreate) -> DocumentOut:
    patient = None
    if payload.patient_id is not None:
        patient = get_patient_by_code(session, payload.patient_id)
        if patient is None:
            raise NotFoundError("PATIENT_NOT_FOUND", "Patient was not found.")
    now = datetime.now(UTC)
    metadata = dict(payload.metadata)
    metadata["embedding_method"] = EMBEDDING_METHOD
    document = Document(
        id=str(uuid4()),
        document_code=next_public_code(session, Document.document_code, "DOC"),
        patient_id=None if patient is None else patient.id,
        document_type=payload.document_type,
        source=payload.source,
        content=payload.content.strip(),
        document_metadata=metadata,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.flush()
    index_document(session, document)
    if payload.document_type == "clinical_note" and patient is not None:
        session.add(
            ClinicalNote(
                id=str(uuid4()),
                note_code=next_public_code(session, ClinicalNote.note_code, "NOTE"),
                patient_id=patient.id,
                document_id=document.id,
                note_type="progress_note",
                content=document.content,
                authored_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
    return get_document_detail(session, document.document_code)
