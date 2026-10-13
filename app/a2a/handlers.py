"""Default A2A handlers for specialized agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.a2a.bus import A2ABus, get_a2a_bus
from app.a2a.protocol import A2AMessage, new_message
from app.core.config import get_settings
from app.services.imaging import build_image_analyzer


def _capability_handler(agent: str) -> Callable[[A2AMessage], A2AMessage | None]:
    def handle(message: A2AMessage) -> A2AMessage | None:
        if message.kind == "capability_query":
            from app.a2a.protocol import AGENT_CAPABILITIES

            return new_message(
                sender=agent,
                recipient=message.sender,
                kind="capability_response",
                payload={"agent": agent, "capabilities": AGENT_CAPABILITIES.get(agent, [])},
                correlation_id=message.correlation_id,
            )
        return None

    return handle


def _imaging_handler(message: A2AMessage) -> A2AMessage | None:
    base = _capability_handler("ImagingAgent")(message)
    if base is not None:
        return base
    if message.kind != "task_request":
        return None
    task = str(message.payload.get("task") or "")
    analyzer = build_image_analyzer(get_settings())
    if task == "analyze_study":
        study_id = str(message.payload.get("study_id") or "IMG-UNKNOWN")
        metadata = {
            str(k): str(v)
            for k, v in dict(message.payload.get("metadata") or {}).items()
        }
        result = analyzer.analyze(study_id, metadata)
        return new_message(
            sender="ImagingAgent",
            recipient=message.sender,
            kind="task_result",
            payload={
                "study_id": result.study_id,
                "observations": list(result.observations),
                "confidence": result.confidence,
                "human_review_required": result.human_review_required,
                "disclaimer": result.disclaimer,
                "backend": result.backend,
            },
            correlation_id=message.correlation_id,
        )
    return new_message(
        sender="ImagingAgent",
        recipient=message.sender,
        kind="task_result",
        payload={"error": f"Unsupported imaging task: {task}"},
        correlation_id=message.correlation_id,
    )


def _generic_task_ack(agent: str) -> Callable[[A2AMessage], A2AMessage | None]:
    def handle(message: A2AMessage) -> A2AMessage | None:
        base = _capability_handler(agent)(message)
        if base is not None:
            return base
        if message.kind == "task_request":
            return new_message(
                sender=agent,
                recipient=message.sender,
                kind="task_result",
                payload={
                    "accepted": True,
                    "agent": agent,
                    "task": message.payload.get("task"),
                    "note": "Handled via A2A; domain work remains in LangGraph/MCP.",
                },
                correlation_id=message.correlation_id,
            )
        return None

    return handle


def register_default_handlers(bus: A2ABus | None = None) -> A2ABus:
    target = bus or get_a2a_bus()
    target.register("PolicyAgent", _generic_task_ack("PolicyAgent"))
    target.register("ClinicalEvidenceAgent", _generic_task_ack("ClinicalEvidenceAgent"))
    target.register("EvidenceVerificationAgent", _generic_task_ack("EvidenceVerificationAgent"))
    target.register("CriticAgent", _generic_task_ack("CriticAgent"))
    target.register("PathwayAgent", _generic_task_ack("PathwayAgent"))
    target.register("AuthorizationAgent", _generic_task_ack("AuthorizationAgent"))
    target.register("Orchestrator", _generic_task_ack("Orchestrator"))
    target.register("ImagingAgent", _imaging_handler)
    return target


def consult_imaging_via_a2a(
    *,
    study_id: str,
    metadata: dict[str, Any],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    bus = register_default_handlers()
    request = new_message(
        sender="Orchestrator",
        recipient="ImagingAgent",
        kind="task_request",
        payload={"task": "analyze_study", "study_id": study_id, "metadata": metadata},
        correlation_id=correlation_id,
    )
    reply = bus.send(request)
    return reply.payload
