"""Typed LangGraph review state."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class ReviewState(TypedDict, total=False):
    run_id: str
    trace_id: str
    patient_id: str
    policy_id: str
    procedure: str
    case_id: str | None
    criteria: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    criterion_results: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    missing_evidence: list[str]
    citations: list[dict[str, Any]]
    human_review_required: bool
    human_review_reason: str
    human_decision: str | None
    paused: bool
    report_summary: str
    evidence_coverage: str
    imaging_consult: dict[str, object]
    a2a_correlation_id: str
    scoring_path: str
    critic_notes: list[str]
    # Notes from the latest verify_evidence pass (merged into critic_notes by the critic).
    citation_check_notes: list[str]
    critic_summary: str
    documentation_pathway: list[dict[str, Any]]
    pathway_summary: str
    readiness_scorecard: dict[str, Any]
    # Supervisor orchestration (evidence-prep routing only — never coverage).
    need_imaging: bool
    retrieve_pass: int
    max_retrieve_passes: int
    orchestration_plan: dict[str, Any]
    senior_assist: dict[str, Any]
    agent_trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
    status: str
