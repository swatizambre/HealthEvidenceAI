"""Query transforms and metadata filters for hybrid RAG."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.rag.types import CandidateHit


@dataclass(frozen=True)
class RetrievalFilters:
    patient_id: str | None = None
    document_type: str | None = None
    policy_id: str | None = None
    source_type: str | None = None
    after: datetime | None = None
    before: datetime | None = None


def transform_query(query: str) -> list[str]:
    """Decompose + multi-angle expand for hybrid retrieval."""
    from app.services.query_rewrite import expand_retrieval_queries

    return expand_retrieval_queries(query, max_queries=6)


def apply_filters(hits: list[CandidateHit], filters: RetrievalFilters) -> list[CandidateHit]:
    kept: list[CandidateHit] = []
    for hit in hits:
        if filters.patient_id and hit.patient_id and hit.patient_id != filters.patient_id:
            continue
        if filters.patient_id and hit.patient_id is None and hit.document_type == "clinical_note":
            continue
        if filters.document_type and hit.document_type != filters.document_type:
            continue
        if filters.policy_id and hit.policy_id and hit.policy_id != filters.policy_id:
            continue
        if filters.source_type and hit.source_type and hit.source_type != filters.source_type:
            continue
        if filters.after and hit.authored_at and hit.authored_at < filters.after:
            continue
        if filters.before and hit.authored_at and hit.authored_at > filters.before:
            continue
        kept.append(hit)
    return kept
