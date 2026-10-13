"""Reciprocal Rank Fusion."""

from __future__ import annotations

from app.services.rag.types import CandidateHit


def reciprocal_rank_fusion(
    ranked_lists: list[list[CandidateHit]],
    *,
    k: int = 60,
) -> list[CandidateHit]:
    scores: dict[str, float] = {}
    best: dict[str, CandidateHit] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            key = hit.chunk_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            previous = best.get(key)
            if previous is None or hit.score > previous.score:
                best[key] = hit
    fused: list[CandidateHit] = []
    for chunk_id, rrf_score in scores.items():
        base = best[chunk_id]
        fused.append(
            CandidateHit(
                document_id=base.document_id,
                chunk_id=base.chunk_id,
                document_type=base.document_type,
                content=base.content,
                score=rrf_score,
                channel="rrf",
                patient_id=base.patient_id,
                policy_id=base.policy_id,
                source_type=base.source_type,
                authored_at=base.authored_at,
            )
        )
    fused.sort(key=lambda hit: (-hit.score, hit.chunk_id))
    return fused
