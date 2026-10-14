"""Product AI scope: hybrid decision-support only (never coverage adjudication)."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings

AI_IN_SCOPE: tuple[dict[str, str], ...] = (
    {
        "id": "retrieve_rank",
        "label": "Retrieve & rank chart evidence",
        "how": "Supervisor-routed hybrid RAG + one critic re-retrieve loop",
        "fallback": "Deterministic keyword / section retrieval",
    },
    {
        "id": "supervisor_graph",
        "label": "Agentic review graph",
        "how": "LangGraph: imaging route, expanded retrieve, critic loop, HITL pause",
        "fallback": "Linear node chain without conditional routes",
    },
    {
        "id": "criteria_checklist",
        "label": "Criteria checklist (support / missing / unknown)",
        "how": (
            "Default: deterministic keyword/lab rules (rule check). "
            "Optional LLM status only when a real model provider is configured"
        ),
        "fallback": "Rules / deterministic eval only",
    },
    {
        "id": "gap_drafts",
        "label": "Documentation gap drafts",
        "how": "Template or LLM coaching lines for missing notes",
        "fallback": "Template + chart cue",
    },
    {
        "id": "senior_review",
        "label": "Senior intelligent review assist",
        "how": "Grounded briefing, focus queue, desk note, documentation action hint",
        "fallback": "Deterministic checklist prioritization",
    },
    {
        "id": "critic_pathway",
        "label": "Critic + documentation pathway",
        "how": "Confidence calibration and ordered next-doc steps",
        "fallback": "Deterministic scorecard",
    },
    {
        "id": "imaging_assist",
        "label": "Imaging assist (MONAI)",
        "how": "Non-diagnostic imaging features via A2A",
        "fallback": "Skip imaging node",
    },
    {
        "id": "help_phrasing",
        "label": "Help desk phrasing",
        "how": "LLM rephrases FAQ from fixed contexts",
        "fallback": "Static FAQ text",
    },
)

AI_OUT_OF_SCOPE: tuple[str, ...] = (
    "Approve or deny coverage / prior authorization",
    "Diagnose, prescribe, or recommend treatment",
    "Submit claims or payer PAS transactions",
    "Replace senior clinician HITL acknowledgment",
    "Autonomous hospital feed decisions (HIS/FHIR is ingest + optional prepare)",
)


def ai_assist_gap_drafts_enabled(settings: Settings) -> bool:
    if settings.ai_gap_drafts is not None:
        return bool(settings.ai_gap_drafts)
    mode = settings.criteria_eval_mode.strip().lower()
    return mode not in {"rules", "deterministic", "rule"}


def describe_ai_scope(settings: Settings) -> dict[str, Any]:
    """Public desk / ops summary of AI configuration."""
    mode = settings.criteria_eval_mode.strip().lower()
    rules_only = mode in {"rules", "deterministic", "rule"}
    return {
        "stance": "hybrid_decision_support",
        "criteria_eval_mode": mode,
        "llm_provider": settings.llm_provider.strip().lower(),
        "llm_failover": settings.llm_provider_chain(),
        "gap_drafts": "ai" if ai_assist_gap_drafts_enabled(settings) else "template",
        "embedding_backend": settings.embedding_backend.strip().lower(),
        "in_scope": list(AI_IN_SCOPE),
        "out_of_scope": list(AI_OUT_OF_SCOPE),
        "human_in_the_loop": True,
        "rules_only": rules_only,
        "disclaimer": (
            "Most checklist scoring is rule-based; optional AI only rephrases or "
            "suggests status when a real model is configured. "
            "It does not approve, deny, diagnose, or submit prior auth."
        ),
    }
