"""Unit tests for AI-primary clinical intelligence scoring."""

from app.core.config import Settings
from app.services.clinical_intelligence import score_criteria_clinical
from app.services.evaluator import CriterionInput, TextRecord


def test_ai_primary_uses_provider_score(monkeypatch) -> None:
    settings = Settings(criteria_eval_mode="ai_primary", llm_provider="local")

    notes = [
        TextRecord(
            content="Patient has documented failed conservative therapy for 12 weeks.",
            document_id="DOC-1",
            chunks=(("CHK-1", "failed conservative therapy for 12 weeks"),),
            source="clinical_note",
        )
    ]
    criteria = [
        CriterionInput(
            code="CRIT-1",
            description="Failed conservative therapy",
            rule={
                "type": "keyword",
                "required_any": ["conservative therapy"],
                "missing_label": "Failed therapy note",
            },
        )
    ]
    scored, path = score_criteria_clinical(settings, criteria, notes, [], retrieved_hits=[])
    # Local provider is the rule engine — not a model path.
    assert path == "rule_check:local"
    assert scored[0].status == "SUPPORTED"
    assert scored[0].evidence
    assert "Rule check" in scored[0].reason
    assert "AI chart check" not in scored[0].reason
    assert "AI check" not in scored[0].reason


def test_rules_mode_skips_ai(monkeypatch) -> None:
    settings = Settings(criteria_eval_mode="rules", llm_provider="local")
    notes = [
        TextRecord(
            content="No therapy documented.",
            document_id="DOC-1",
            chunks=(("CHK-1", "No therapy documented."),),
            source="clinical_note",
        )
    ]
    criteria = [
        CriterionInput(
            code="CRIT-1",
            description="Failed conservative therapy",
            rule={
                "type": "keyword",
                "required_any": ["conservative therapy"],
                "missing_label": "Failed therapy note",
            },
        )
    ]
    scored, path = score_criteria_clinical(settings, criteria, notes, [], retrieved_hits=[])
    assert path == "rules"
    assert scored[0].status == "MISSING"
