"""Hybrid RAG pipeline: transform → dense+lexical → RRF → rerank → filter."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import Document, DocumentChunk, Patient
from app.models.entities import InsurancePolicy
from app.services.prompt_guard import inspect_retrieved_content
from app.services.rag.dense import dense_search
from app.services.rag.embeddings import tokenize
from app.services.rag.filters import RetrievalFilters, apply_filters, transform_query
from app.services.rag.fusion import reciprocal_rank_fusion
from app.services.rag.lexical import lexical_search
from app.services.rag.rerank import rerank
from app.services.rag.types import ChunkRecord, RetrievalHit


def load_corpus(session: Session) -> list[ChunkRecord]:
    rows = session.execute(
        select(DocumentChunk, Document, Patient, InsurancePolicy)
        .join(Document, DocumentChunk.document_id == Document.id)
        .outerjoin(Patient, Document.patient_id == Patient.id)
        .outerjoin(InsurancePolicy, InsurancePolicy.document_id == Document.id)
    ).all()
    corpus: list[ChunkRecord] = []
    for chunk, document, patient, policy in rows:
        corpus.append(
            ChunkRecord(
                document_id=document.document_code,
                chunk_id=chunk.chunk_code,
                document_type=document.document_type,
                content=chunk.content,
                embedding=chunk.embedding,
                patient_id=patient.patient_code if patient else None,
                policy_id=policy.policy_code if policy else None,
                source_type=document.source,
                authored_at=document.created_at,
            )
        )
    return corpus


def hybrid_search(
    session: Session,
    *,
    query: str,
    patient_code: str | None = None,
    document_type: str | None = None,
    policy_id: str | None = None,
    source_type: str | None = None,
    limit: int = 5,
    settings: Settings | None = None,
) -> list[RetrievalHit]:
    cfg = settings or get_settings()
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []
    corpus = load_corpus(session)
    filters = RetrievalFilters(
        patient_id=patient_code,
        document_type=document_type,
        policy_id=policy_id,
        source_type=source_type,
    )
    queries = transform_query(query)
    lexical_lists = []
    dense_lists = []
    for sub in queries:
        lexical_lists.append(lexical_search(sub, corpus, limit=max(limit * 4, 20)))
        dense_lists.append(dense_search(sub, corpus, limit=max(limit * 4, 20), settings=cfg))
    fused = reciprocal_rank_fusion([*lexical_lists, *dense_lists])
    filtered = apply_filters(fused, filters)
    _ = [inspect_retrieved_content(hit.content) for hit in filtered]
    ranked = rerank(query, filtered, limit=max(limit * 3, 15))
    # Drop RRF noise with no lexical overlap (prevents fabricated weak hits).
    grounded = [
        hit
        for hit in ranked
        if query_tokens & set(tokenize(hit.content))
    ][:limit]
    return [
        RetrievalHit(
            document_id=hit.document_id,
            chunk_id=hit.chunk_id,
            document_type=hit.document_type,
            content=hit.content,
            score=round(hit.score, 6),
        )
        for hit in grounded
    ]


# Primary public name used across the app.
search_chunks = hybrid_search
