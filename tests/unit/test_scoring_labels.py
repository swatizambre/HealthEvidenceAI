"""Honest rule-check vs AI-check path labels."""

from app.services.scoring_labels import (
    is_model_assist_source,
    is_model_scoring_path,
    scoring_method_label,
)


def test_local_and_rules_are_rule_check() -> None:
    for path in ("rules", "rules_fallback", "rule_check:local", ""):
        assert not is_model_scoring_path(path)
        assert scoring_method_label(path) == "Rule check"


def test_real_providers_are_ai_check() -> None:
    for path in ("ai_clinical:ollama", "ai_clinical:gemini", "ai_clinical:openai"):
        assert is_model_scoring_path(path)
        assert scoring_method_label(path) == "AI check"


def test_local_draft_source_is_not_model() -> None:
    assert not is_model_assist_source("ai:local")
    assert not is_model_assist_source("template")
    assert is_model_assist_source("ai:ollama")
    assert is_model_assist_source("ai:gemini")
