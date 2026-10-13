"""Healthcare MCP tool implementations (permission-gated domain services)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.safety import PROTOTYPE_BANNER
from app.db.repository import get_policy_by_code, list_criteria, list_labs, list_medications, list_notes
from app.services.audit import record_audit
from app.services.permissions import (
    EVIDENCE_READ,
    EVIDENCE_SEARCH,
    HUMAN_REVIEW_CREATE,
    PATIENT_READ,
    POLICY_READ,
    require_permission,
)
from app.services.rag.pipeline import hybrid_search
from app.services.records import get_patient_timeline as load_timeline
from app.services.records import require_patient

TOOL_PERMISSIONS: dict[str, str] = {
    "get_patient_record": PATIENT_READ,
    "get_patient_timeline": PATIENT_READ,
    "get_policy": POLICY_READ,
    "get_policy_criteria": POLICY_READ,
    "search_clinical_evidence": EVIDENCE_SEARCH,
    "get_evidence_chunk": EVIDENCE_READ,
    "create_human_review": HUMAN_REVIEW_CREATE,
}


def list_tool_names() -> list[str]:
    return sorted(TOOL_PERMISSIONS)


def call_tool(
    session: Session,
    *,
    tool_name: str,
    agent: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    permission = TOOL_PERMISSIONS.get(tool_name)
    if permission is None:
        raise KeyError(f"Unknown tool: {tool_name}")
    require_permission(agent, permission, session=session)
    handler = TOOL_HANDLERS[tool_name]
    return handler(session, **arguments)


def get_patient_record(session: Session, *, patient_id: str) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    return {
        "patient_id": patient.patient_code,
        "conditions": list(patient.conditions),
        "medication_count": len(list_medications(session, patient.id)),
        "lab_count": len(list_labs(session, patient.id)),
        "note_count": len(list_notes(session, patient.id)),
        "disclaimer": PROTOTYPE_BANNER,
    }


def get_patient_timeline(session: Session, *, patient_id: str) -> dict[str, Any]:
    timeline = load_timeline(session, patient_id)
    return {
        "patient_id": timeline.patient_id,
        "events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "description": event.description,
            }
            for event in timeline.events[:50]
        ],
        "disclaimer": PROTOTYPE_BANNER,
    }


def get_policy(session: Session, *, policy_id: str) -> dict[str, Any]:
    from app.core.exceptions import NotFoundError

    policy = get_policy_by_code(session, policy_id)
    if policy is None:
        raise NotFoundError("POLICY_NOT_FOUND", "Policy was not found.")
    return {
        "policy_id": policy.policy_code,
        "title": policy.title,
        "payer_name": policy.payer_name,
        "procedure": policy.procedure_name,
        "version": policy.version,
        "content": policy.content,
        "disclaimer": PROTOTYPE_BANNER,
    }


def get_policy_criteria(session: Session, *, policy_id: str) -> dict[str, Any]:
    from app.core.exceptions import NotFoundError

    policy = get_policy_by_code(session, policy_id)
    if policy is None:
        raise NotFoundError("POLICY_NOT_FOUND", "Policy was not found.")
    criteria = list_criteria(session, policy.id)
    return {
        "policy_id": policy.policy_code,
        "criteria": [
            {
                "criterion_id": item.criterion_code,
                "description": item.description,
                "position": item.position,
                "rule": dict(item.rule),
            }
            for item in criteria
        ],
        "disclaimer": PROTOTYPE_BANNER,
    }


def search_clinical_evidence(
    session: Session,
    *,
    query: str,
    patient_id: str | None = None,
    document_type: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    hits = hybrid_search(
        session,
        query=query,
        patient_code=patient_id,
        document_type=document_type,
        limit=limit,
        settings=get_settings(),
    )
    return {
        "query": query,
        "hits": [
            {
                "document_id": hit.document_id,
                "chunk_id": hit.chunk_id,
                "document_type": hit.document_type,
                "content": hit.content,
                "score": hit.score,
            }
            for hit in hits
        ],
        "disclaimer": PROTOTYPE_BANNER,
    }


def get_evidence_chunk(session: Session, *, chunk_id: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.exceptions import NotFoundError
    from app.models import Document, DocumentChunk

    row = session.execute(
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.chunk_code == chunk_id)
    ).first()
    if row is None:
        raise NotFoundError("CHUNK_NOT_FOUND", "Evidence chunk was not found.")
    chunk, document = row
    return {
        "chunk_id": chunk.chunk_code,
        "document_id": document.document_code,
        "document_type": document.document_type,
        "content": chunk.content,
        "disclaimer": PROTOTYPE_BANNER,
    }


def create_human_review(
    session: Session,
    *,
    run_id: str,
    patient_id: str,
    reason: str,
    decision: str = "pending",
    actor: str = "human_reviewer",
) -> dict[str, Any]:
    # Tool path cannot finalize senior acknowledgment — HTTP layer enforces RBAC;
    # coerce unexpected decisions to pending so agent callers cannot auto-ack.
    safe_decision = str(decision or "pending").strip().lower()
    if safe_decision not in {"pending", "acknowledged", "needs_documentation"}:
        safe_decision = "pending"
    audit_actor = str(actor or "human_reviewer").strip()[:64] or "human_reviewer"
    event = record_audit(
        session,
        action="human_review",
        actor=audit_actor,
        resource_type="review_run",
        resource_id=run_id,
        status=safe_decision,
        detail=f"patient={patient_id};reason={reason[:200]}",
    )
    return {
        "run_id": run_id,
        "patient_id": patient_id,
        "reason": reason,
        "decision": safe_decision,
        "audit_id": event.id,
        "disclaimer": PROTOTYPE_BANNER,
    }


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_patient_record": get_patient_record,
    "get_patient_timeline": get_patient_timeline,
    "get_policy": get_policy,
    "get_policy_criteria": get_policy_criteria,
    "search_clinical_evidence": search_clinical_evidence,
    "get_evidence_chunk": get_evidence_chunk,
    "create_human_review": create_human_review,
}
