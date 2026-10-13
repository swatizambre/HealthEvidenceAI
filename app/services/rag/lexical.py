"""Lexical retrieval over sparse vectors."""

from __future__ import annotations

from app.services.rag.embeddings import parse_embedding, sparse_cosine, sparse_embed
from app.services.rag.types import CandidateHit, ChunkRecord


def lexical_search(query: str, corpus: list[ChunkRecord], *, limit: int = 20) -> list[CandidateHit]:
    query_vec = sparse_embed(query)
    scored: list[CandidateHit] = []
    for item in corpus:
        sparse, _ = parse_embedding(item.embedding)
        score = sparse_cosine(query_vec, sparse)
        if score <= 0.0:
            continue
        scored.append(
            CandidateHit(
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                document_type=item.document_type,
                content=item.content,
                score=score,
                channel="lexical",
                patient_id=item.patient_id,
                policy_id=item.policy_id,
                source_type=item.source_type,
                authored_at=item.authored_at,
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return scored[:limit]
