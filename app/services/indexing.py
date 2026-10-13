"""Chunk and embed a stored document into the vector table."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.chunking import chunk_text
from app.services.embeddings import embed


def index_document(session: Session, document: Document) -> list[DocumentChunk]:
    """Replace chunks for one document. Content is stored; it is not logged."""
    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    created: list[DocumentChunk] = []
    for index, text in enumerate(chunk_text(document.content), start=1):
        chunk = DocumentChunk(
            id=str(uuid4()),
            chunk_code=f"{document.document_code}-{index:02d}",
            document_id=document.id,
            chunk_index=index,
            content=text,
            embedding=embed(text),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        session.add(chunk)
        created.append(chunk)
    return created
