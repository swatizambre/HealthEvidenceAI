"""Authorization review entrypoint — LangGraph only."""

from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.types import Command
from sqlalchemy.orm import Session

from app.agents.checkpoints import get_checkpointer, thread_config
from app.agents.graph import build_review_graph
from app.agents.runs import load_run, save_run
from app.agents.state import ReviewState
from app.core.config import get_settings
from app.core.exceptions import AppError, NotFoundError
from app.core.safety import DISCLAIMER, enforce_decision_support
from app.schemas.api import (
    AgentTraceStep,
    AuthorizationReviewRequest,
    AuthorizationReviewResponse,
    ContradictionOut,
    CriterionResult,
    EvidenceRef,
    HumanReviewResumeRequest,
    PathwayStepOut,
    ReadinessScorecardOut,
    SeniorAssistSnapshot,
)
from app.services.audit import record_audit
from app.services.observability import get_trace, new_run_id, new_trace_id
from app.services.permissions import require_tool_permission

logger = logging.getLogger("healthevidence.review")


def review_authorization(
    session: Session,
    payload: AuthorizationReviewRequest,
    *,
    auto_complete_human_review: bool = False,
) -> AuthorizationReviewResponse:
    """Run the senior agent graph. Senior HITL is never auto-acknowledged."""
    require_tool_permission("AuthorizationAgent", "read", "policies", session=session)
    require_tool_permission("AuthorizationAgent", "write", "review_draft", session=session)
    # interactive or not — junior desks cannot skip senior sign-off.
    auto_complete_human_review = False
    run_id = new_run_id()
    trace_id = new_trace_id()
    initial: ReviewState = {
        "run_id": run_id,
        "trace_id": trace_id,
        "patient_id": payload.patient_id,
        "policy_id": payload.policy_id,
        "procedure": payload.procedure,
        "case_id": payload.case_id,
        "agent_trace": [],
        "errors": [],
        "human_decision": "acknowledged" if auto_complete_human_review else None,
        "paused": False,
        "retrieve_pass": 0,
        "max_retrieve_passes": 2,
        "need_imaging": False,
    }
    settings = get_settings()
    graph = build_review_graph(session, settings)
    config = thread_config(run_id)
    final_state: dict[str, Any] = dict(graph.invoke(initial, config))
    final_state = _normalize_graph_state(final_state, run_id=run_id, trace_id=trace_id)
    save_run(run_id, final_state, session)
    if _is_awaiting(final_state):
        response = _to_response(final_state, awaiting=True)
        _sync_case_lifecycle(session, response)
        return response
    response = _to_response(final_state)
    enforce_decision_support(response.model_dump(mode="json"))
    _sync_case_lifecycle(session, response)
    _audit(session, response, final_state)
    return response


def resume_review(
    session: Session,
    run_id: str,
    payload: HumanReviewResumeRequest,
) -> AuthorizationReviewResponse:
    state = load_run(run_id, session)
    if state is None:
        raise NotFoundError("REVIEW_RUN_NOT_FOUND", "Review run was not found.")

    assist_payload = (
        payload.senior_assist.model_dump(mode="json") if payload.senior_assist is not None else None
    )
    resume_body: dict[str, Any] = {
        "decision": payload.decision,
        "notes": payload.notes or "",
    }
    if assist_payload is not None:
        resume_body["senior_assist"] = assist_payload

    settings = get_settings()
    config = thread_config(run_id)
    checkpointer = get_checkpointer()
    has_checkpoint = checkpointer.get_tuple(config) is not None  # type: ignore[arg-type]

    if has_checkpoint:
        graph = build_review_graph(session, settings)
        final_state = dict(graph.invoke(Command(resume=resume_body), config))
        final_state = _normalize_graph_state(
            final_state,
            run_id=run_id,
            trace_id=str(state.get("trace_id") or ""),
        )
        if assist_payload is not None:
            final_state["senior_assist"] = assist_payload
        save_run(run_id, final_state, session)
        if _is_awaiting(final_state):
            response = _to_response(final_state, awaiting=True)
            _sync_case_lifecycle(session, response, clinician_decision=payload.decision)
            return response
        response = _to_response(final_state)
        enforce_decision_support(response.model_dump(mode="json"))
        _sync_case_lifecycle(session, response, clinician_decision=payload.decision)
        _audit(session, response, final_state)
        return response

    # Cross-restart fallback: no in-memory interrupt thread — finish from DB state.
    return _resume_from_persisted_state(session, run_id, state, payload, assist_payload)


def _resume_from_persisted_state(
    session: Session,
    run_id: str,
    state: dict[str, Any],
    payload: HumanReviewResumeRequest,
    assist_payload: dict[str, Any] | None,
) -> AuthorizationReviewResponse:
    from app.agents.nodes import generate_report, human_review_gate

    state["human_decision"] = payload.decision
    state["paused"] = False
    if assist_payload is not None:
        state["senior_assist"] = assist_payload
    if payload.notes:
        state["human_review_reason"] = (
            f"{state.get('human_review_reason') or ''}; reviewer={payload.notes}"
        ).strip("; ")
    settings = get_settings()
    mid = human_review_gate(state, session, settings)
    state.update(mid)
    if state.get("paused"):
        save_run(run_id, state, session)
        response = _to_response(state, awaiting=True)
        _sync_case_lifecycle(session, response, clinician_decision=payload.decision)
        return response
    end = generate_report(state, session, settings)
    state.update(end)
    save_run(run_id, state, session)
    response = _to_response(state)
    enforce_decision_support(response.model_dump(mode="json"))
    _sync_case_lifecycle(session, response, clinician_decision=payload.decision)
    _audit(session, response, state)
    return response


def _normalize_graph_state(
    final_state: dict[str, Any], *, run_id: str, trace_id: str
) -> dict[str, Any]:
    """Strip LangGraph interrupt chrome and pin identity fields for ReviewRun JSON."""
    cleaned = {key: value for key, value in final_state.items() if key != "__interrupt__"}
    cleaned["run_id"] = run_id or str(cleaned.get("run_id") or "")
    if trace_id:
        cleaned["trace_id"] = trace_id
    if final_state.get("__interrupt__") or cleaned.get("status") == "awaiting_human_review":
        cleaned["paused"] = True
    return cleaned


def _is_awaiting(state: dict[str, Any]) -> bool:
    return bool(state.get("paused") or state.get("status") == "awaiting_human_review")


def _sync_case_lifecycle(
    session: Session,
    response: AuthorizationReviewResponse,
    *,
    clinician_decision: str | None = None,
) -> None:
    from app.services.records import update_case_lifecycle

    if response.awaiting_human_review:
        status = "ready_for_human"
        note = response.human_review_reason or "Awaiting clinician checklist acknowledgment"
    elif clinician_decision == "needs_documentation" or (
        response.human_review_required and response.missing_evidence
    ):
        status = "needs_documentation"
        note = "; ".join(response.missing_evidence[:3]) or response.human_review_reason
    elif response.human_review_required:
        status = "ready_for_human" if not clinician_decision else "closed_as_draft"
        note = response.human_review_reason or "Clinician acknowledgment recorded"
        if clinician_decision == "acknowledged":
            status = "closed_as_draft"
    else:
        status = "closed_as_draft"
        note = "Checklist looks complete in the chart (draft only — not an approval)"
    update_case_lifecycle(
        session,
        case_code=response.case_id,
        status=status,
        run_id=response.run_id or None,
        note=note,
    )


def _audit(
    session: Session, response: AuthorizationReviewResponse, state: dict[str, Any]
) -> None:
    record_audit(
        session,
        action="authorization_review",
        actor="AuthorizationAgent",
        resource_type="patient",
        resource_id=response.patient_id,
        status="completed" if not response.awaiting_human_review else "paused",
        detail=(
            f"run={response.run_id};criteria={len(response.criteria)};"
            f"human_review={response.human_review_required}"
        ),
    )
    logger.info(
        "authorization_review_completed run_id=%s criteria=%s human_review_required=%s",
        response.run_id,
        len(response.criteria),
        response.human_review_required,
    )
    enforce_decision_support(response.model_dump(mode="json"))


def _to_response(
    state: dict[str, Any], *, awaiting: bool = False
) -> AuthorizationReviewResponse:
    criteria = [
        CriterionResult(
            criterion_id=str(item["criterion_id"]),
            criterion=str(item["criterion"]),
            status=_status(str(item["status"])),
            evidence=[_evidence(entry) for entry in item.get("evidence") or []],
            reason=str(item.get("reason") or ""),
            confidence=(
                float(item["confidence"])
                if item.get("confidence") is not None
                else None
            ),
        )
        for item in state.get("criterion_results") or []
    ]
    contradictions = [
        ContradictionOut(
            criterion=str(item.get("criterion") or ""),
            description=str(item.get("description") or item.get("evidence_b") or ""),
            evidence=[_evidence(entry) for entry in item.get("evidence") or []],
            conflict=bool(item.get("conflict", True)),
            evidence_a=str(item.get("evidence_a") or ""),
            evidence_b=str(item.get("evidence_b") or ""),
            resolution=str(item.get("resolution") or "human_review"),
        )
        for item in state.get("contradictions") or []
    ]
    citations = [_evidence(entry) for entry in state.get("citations") or []]
    trace_steps = [
        AgentTraceStep(
            agent=str(step.get("agent") or ""),
            node=str(step.get("node") or ""),
            detail=str(step.get("detail") or ""),
            status=str(step.get("status") or "ok"),
        )
        for step in state.get("agent_trace") or []
        if isinstance(step, dict)
    ]
    run_id = str(state.get("run_id") or "")
    response = AuthorizationReviewResponse(
        case_id=state.get("case_id"),
        patient_id=str(state.get("patient_id") or ""),
        policy_id=str(state.get("policy_id") or ""),
        procedure=str(state.get("procedure") or ""),
        review_type="evidence_review",
        criteria=criteria,
        missing_evidence=list(state.get("missing_evidence") or []),
        contradictions=contradictions,
        human_review_required=bool(state.get("human_review_required")),
        awaiting_human_review=awaiting or bool(state.get("paused")),
        evidence_coverage=_coverage(str(state.get("evidence_coverage") or "NONE")),
        citations=citations,
        disclaimer=DISCLAIMER,
        run_id=run_id,
        trace_id=str(state.get("trace_id") or ""),
        scoring_path=str(state.get("scoring_path") or ""),
        report_summary=str(state.get("report_summary") or ""),
        human_review_reason=str(state.get("human_review_reason") or ""),
        agent_trace=trace_steps,
        observability=get_trace(run_id),
        evidence_panel=[
            {
                "document_id": str(item.get("document_id") or ""),
                "chunk_id": str(item.get("chunk_id") or ""),
                "criterion_id": str(item.get("criterion_id") or ""),
                "score": item.get("score"),
                "content": str(item.get("content") or "")[:500],
            }
            for item in state.get("evidence") or []
        ],
        critic_summary=str(state.get("critic_summary") or ""),
        critic_notes=[str(item) for item in state.get("critic_notes") or []],
        documentation_pathway=[
            PathwayStepOut(
                step=int(step.get("step") or 0),
                title=str(step.get("title") or ""),
                detail=str(step.get("detail") or ""),
                agent=str(step.get("agent") or ""),
                focus=str(step.get("focus") or ""),
                priority=str(step.get("priority") or "info"),
                criterion_id=str(step.get("criterion_id") or ""),
                confidence=(
                    float(step["confidence"])
                    if step.get("confidence") is not None
                    else None
                ),
            )
            for step in state.get("documentation_pathway") or []
            if isinstance(step, dict)
        ],
        pathway_summary=str(state.get("pathway_summary") or ""),
        readiness_scorecard=(
            ReadinessScorecardOut.model_validate(state["readiness_scorecard"])
            if isinstance(state.get("readiness_scorecard"), dict)
            else None
        ),
        senior_assist=(
            SeniorAssistSnapshot.model_validate(state["senior_assist"])
            if isinstance(state.get("senior_assist"), dict)
            else None
        ),
    )
    return response


def _evidence(entry: object) -> EvidenceRef:
    if isinstance(entry, dict):
        return EvidenceRef(
            document_id=str(entry.get("document_id") or ""),
            chunk_id=str(entry.get("chunk_id") or ""),
            source=str(entry.get("source") or "evidence"),
            text_reference=str(entry.get("text_reference") or entry.get("content") or "")[:500],
        )
    return EvidenceRef(
        document_id=getattr(entry, "document_id", ""),
        chunk_id=getattr(entry, "chunk_id", ""),
        source=getattr(entry, "source", "evidence"),
        text_reference=getattr(entry, "text_reference", ""),
    )


def _status(value: str) -> Literal["SUPPORTED", "NOT_SUPPORTED", "MISSING", "UNKNOWN"]:
    statuses: dict[str, Literal["SUPPORTED", "NOT_SUPPORTED", "MISSING", "UNKNOWN"]] = {
        "SUPPORTED": "SUPPORTED",
        "NOT_SUPPORTED": "NOT_SUPPORTED",
        "MISSING": "MISSING",
        "UNKNOWN": "UNKNOWN",
    }
    try:
        return statuses[value]
    except KeyError as exc:
        raise AppError(
            "UNSAFE_OUTPUT_BLOCKED",
            "The review was blocked because a criterion status was not recognized.",
            500,
        ) from exc


def _coverage(value: str) -> Literal["NONE", "AVAILABLE", "COMPLETE"]:
    labels: dict[str, Literal["NONE", "AVAILABLE", "COMPLETE"]] = {
        "NONE": "NONE",
        "AVAILABLE": "AVAILABLE",
        "COMPLETE": "COMPLETE",
    }
    try:
        return labels[value]
    except KeyError as exc:
        raise AppError(
            "UNSAFE_OUTPUT_BLOCKED",
            "The review was blocked because evidence coverage was not recognized.",
            500,
        ) from exc
