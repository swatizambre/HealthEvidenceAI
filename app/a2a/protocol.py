"""Agent-to-Agent (A2A) message protocol for specialized healthcare agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

AgentName = Literal[
    "Orchestrator",
    "PolicyAgent",
    "ClinicalEvidenceAgent",
    "EvidenceVerificationAgent",
    "CriticAgent",
    "PathwayAgent",
    "ImagingAgent",
    "AuthorizationAgent",
]

MessageKind = Literal[
    "capability_query",
    "capability_response",
    "task_request",
    "task_result",
    "escalation",
    "ack",
]


@dataclass
class A2AMessage:
    message_id: str
    correlation_id: str
    sender: str
    recipient: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_message(
    *,
    sender: str,
    recipient: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> A2AMessage:
    return A2AMessage(
        message_id=str(uuid4()),
        correlation_id=correlation_id or str(uuid4()),
        sender=sender,
        recipient=recipient,
        kind=kind,
        payload=payload or {},
    )


AGENT_CAPABILITIES: dict[str, list[str]] = {
    "PolicyAgent": ["load_policy", "decompose_criteria"],
    "ClinicalEvidenceAgent": ["retrieve_evidence", "identify_missing", "multi_query_rag"],
    "EvidenceVerificationAgent": ["verify_citations", "detect_contradictions"],
    "CriticAgent": ["calibrate_confidence", "reflect_weak_support"],
    "PathwayAgent": ["build_documentation_pathway", "rank_next_actions"],
    "ImagingAgent": ["analyze_study_metadata", "compare_studies", "monai_isolated_stats"],
    "AuthorizationAgent": ["create_human_review", "finalize_report"],
    "Orchestrator": ["route", "aggregate", "readiness_scorecard"],
}
