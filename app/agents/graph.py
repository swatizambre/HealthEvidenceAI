"""LangGraph authorization review orchestrator — supervisor-routed evidence prep."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agents.nodes import (
    build_pathway_node,
    check_contradictions,
    critic_reflect_node,
    evaluate_criteria_node,
    generate_report,
    human_review_gate,
    imaging_a2a_consult,
    load_case,
    load_policy,
    retrieve_evidence,
    supervisor_plan,
    targeted_retrieve_evidence,
    verify_evidence,
)
from app.agents.checkpoints import get_checkpointer
from app.agents.state import ReviewState
from app.agents.supervisor import should_rereetrieve
from app.core.config import Settings, get_settings

NodeFn = Callable[[dict[str, Any], Session, Settings], dict[str, Any]]


def _wrap(fn: NodeFn, session: Session, settings: Settings) -> Any:
    def node(state: ReviewState) -> dict[str, Any]:
        return fn(dict(state), session, settings)

    return node


def build_review_graph(session: Session, settings: Settings | None = None) -> Any:
    """Compile the best-fit agentic DAG for documentation readiness (not coverage).

    Flow:
      load → policy → supervisor → retrieve
        → (imaging | skip) → score → verify → contradictions → critic
        → (one targeted re-retrieve → score…) | pathway → HITL → report

    HITL uses LangGraph interrupt (MemorySaver thread_id=run_id) with ReviewRun
    JSON as cross-restart fallback.
    """
    cfg = settings or get_settings()
    graph: StateGraph[ReviewState] = StateGraph(ReviewState)
    graph.add_node("load_case", _wrap(load_case, session, cfg))
    graph.add_node("load_policy", _wrap(load_policy, session, cfg))
    graph.add_node("supervisor_plan", _wrap(supervisor_plan, session, cfg))
    graph.add_node("retrieve_evidence", _wrap(retrieve_evidence, session, cfg))
    graph.add_node("imaging_a2a_consult", _wrap(imaging_a2a_consult, session, cfg))
    graph.add_node("evaluate_criteria", _wrap(evaluate_criteria_node, session, cfg))
    graph.add_node("verify_evidence", _wrap(verify_evidence, session, cfg))
    graph.add_node("check_contradictions", _wrap(check_contradictions, session, cfg))
    graph.add_node("critic_reflect", _wrap(critic_reflect_node, session, cfg))
    graph.add_node("targeted_retrieve", _wrap(targeted_retrieve_evidence, session, cfg))
    graph.add_node("build_pathway", _wrap(build_pathway_node, session, cfg))
    graph.add_node("human_review", _wrap(human_review_gate, session, cfg))
    graph.add_node("generate_report", _wrap(generate_report, session, cfg))

    graph.set_entry_point("load_case")
    graph.add_edge("load_case", "load_policy")
    graph.add_edge("load_policy", "supervisor_plan")
    graph.add_edge("supervisor_plan", "retrieve_evidence")

    def after_retrieve(state: ReviewState) -> str:
        if state.get("need_imaging"):
            return "imaging"
        return "score"

    graph.add_conditional_edges(
        "retrieve_evidence",
        after_retrieve,
        {"imaging": "imaging_a2a_consult", "score": "evaluate_criteria"},
    )
    graph.add_edge("imaging_a2a_consult", "evaluate_criteria")
    graph.add_edge("evaluate_criteria", "verify_evidence")
    graph.add_edge("verify_evidence", "check_contradictions")
    graph.add_edge("check_contradictions", "critic_reflect")

    def after_critic(state: ReviewState) -> str:
        if should_rereetrieve(dict(state)):
            return "rereetrieve"
        return "pathway"

    graph.add_conditional_edges(
        "critic_reflect",
        after_critic,
        {"rereetrieve": "targeted_retrieve", "pathway": "build_pathway"},
    )
    # One budgeted loop: targeted retrieve rejoins scoring (retrieve_pass blocks a second loop).
    graph.add_edge("targeted_retrieve", "evaluate_criteria")
    graph.add_edge("build_pathway", "human_review")

    def after_human(state: ReviewState) -> str:
        # Interrupt path never returns paused; legacy soft-pause still ends here.
        if state.get("paused"):
            return "pause"
        return "continue"

    graph.add_conditional_edges(
        "human_review",
        after_human,
        {"pause": END, "continue": "generate_report"},
    )
    graph.add_edge("generate_report", END)
    return graph.compile(checkpointer=get_checkpointer())
