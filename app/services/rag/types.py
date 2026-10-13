"""Shared RAG datatypes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChunkRecord:
    document_id: str
    chunk_id: str
    document_type: str
    content: str
    embedding: object
    patient_id: str | None = None
    policy_id: str | None = None
    source_type: str | None = None
    authored_at: datetime | None = None


@dataclass(frozen=True)
class CandidateHit:
    document_id: str
    chunk_id: str
    document_type: str
    content: str
    score: float
    channel: str
    patient_id: str | None = None
    policy_id: str | None = None
    source_type: str | None = None
    authored_at: datetime | None = None


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    document_type: str
    content: str
    score: float
