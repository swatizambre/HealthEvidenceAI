"""Dense retrieval over fixed-dim vectors."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.rag.embeddings import dense_cosine, dense_embed, parse_embedding
from app.services.rag.types import CandidateHit, ChunkRecord


def dense_search(
    query: str,
    corpus: list[ChunkRecord],
    *,
    limit: int = 20,
    settings: Settings | None = None,
) -> list[CandidateHit]:
    cfg = settings or get_settings()
    query_vec = dense_embed(query, cfg)
    scored: list[CandidateHit] = []
    for item in corpus:
        _, dense = parse_embedding(item.embedding)
        if not dense:
            # Rebuild dense vectors from chunk text when dense channel is absent.
            dense = dense_embed(item.content, cfg)
        score = dense_cosine(query_vec, dense)
        if score <= 0.0:
            continue
        scored.append(
            CandidateHit(
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                document_type=item.document_type,
                content=item.content,
                score=score,
                channel="dense",
                patient_id=item.patient_id,
                policy_id=item.policy_id,
                source_type=item.source_type,
                authored_at=item.authored_at,
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return scored[:limit]
