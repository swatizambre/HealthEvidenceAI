"""Honest labels for rule-driven vs model-driven checklist scoring.

Default desk path is deterministic rules (keyword/lab checks). The local
"provider" only rephrases those results — it is not a model. Reserve "AI check"
for providers that actually call an LLM for criterion status.
"""

from __future__ import annotations


def is_model_scoring_path(path: str | None) -> bool:
    """True only when scoring_path names a real LLM provider (not local/rules)."""
    value = (path or "").strip().lower()
    if not value:
        return False
    if value.startswith("rules") or value.startswith("rule_check"):
        return False
    if value.startswith("ai_clinical:"):
        provider = value.split(":", 1)[-1].strip()
        return provider not in {"", "local"}
    return False


def is_model_assist_source(source: str | None) -> bool:
    """True for draft_source / senior assist sources that used a real LLM."""
    value = (source or "").strip().lower()
    if value.startswith("ai:"):
        provider = value.split(":", 1)[-1].strip()
        return provider not in {"", "local"}
    if value.startswith("ai_"):
        return "local" not in value
    return False


def scoring_method_label(path: str | None) -> str:
    """Short method name for briefs and doctor packets."""
    return "AI check" if is_model_scoring_path(path) else "Rule check"


def scoring_assist_label(path: str | None) -> str:
    """Phrase for the desk prepare brief."""
    return "AI check" if is_model_scoring_path(path) else "Rule check"
