"""Lightweight cross-channel reranker (token overlap + fused score)."""

from __future__ import annotations

from app.services.rag.embeddings import tokenize
from app.services.rag.types import CandidateHit


def rerank(query: str, hits: list[CandidateHit], *, limit: int = 5) -> list[CandidateHit]:
    query_tokens = set(tokenize(query))
    rescored: list[CandidateHit] = []
    for hit in hits:
        overlap = len(query_tokens & set(tokenize(hit.content)))
        score = float(hit.score) + 0.05 * overlap
        rescored.append(
            CandidateHit(
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                document_type=hit.document_type,
                content=hit.content,
                score=score,
                channel="rerank",
                patient_id=hit.patient_id,
                policy_id=hit.policy_id,
                source_type=hit.source_type,
                authored_at=hit.authored_at,
            )
        )
    rescored.sort(key=lambda item: (-item.score, item.chunk_id))
    return rescored[:limit]
