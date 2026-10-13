"""The one-command demo prints computed review counts."""

import pytest
from app.cli.demo import format_demo, run_demo
from app.core.safety import DISCLAIMER
from app.schemas.api import AuthorizationReviewResponse, CriterionResult, EvidenceRef
from tests.fakes.llm import TestDoubleLLM


def test_format_demo_uses_the_review_counts() -> None:
    evidence = EvidenceRef(
        document_id="DOC-N000001",
        chunk_id="DOC-N000001-01",
        source="clinical_note",
        text_reference="lumbar radiculopathy is documented",
    )
    result = AuthorizationReviewResponse(
        case_id="PA-000001",
        patient_id="PAT-000001",
        policy_id="POL-000001",
        procedure="Lumbar spine MRI",
        review_type="evidence_review",
        criteria=[
            CriterionResult(
                criterion_id="CRIT-LUMBAR-01",
                criterion="Diagnosis",
                status="SUPPORTED",
                evidence=[evidence],
                reason="cited",
            ),
            CriterionResult(
                criterion_id="CRIT-LUMBAR-04",
                criterion="Lab",
                status="MISSING",
                evidence=[],
                reason="missing",
            ),
        ],
        missing_evidence=["Required laboratory result"],
        contradictions=[],
        human_review_required=True,
        evidence_coverage="AVAILABLE",
        citations=[evidence],
        disclaimer=DISCLAIMER,
    )
    text = format_demo(result)
    assert "Patient: PAT-000001" in text
    assert "Human review required: YES" in text
    assert "Evidence coverage: AVAILABLE" in text
    assert "Autonomous clinical decision: NO" in text
    assert "SUPPORTED:" in text
    assert "MISSING:" in text


def test_run_demo_exits_successfully(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    double = TestDoubleLLM()

    def _double(settings: object = None, provider: str | None = None) -> TestDoubleLLM:
        del settings, provider
        return double

    def _failover(settings: object, prompt: str, contexts: list[str]) -> tuple[str, str]:
        del settings
        return double.complete_report(prompt, contexts), "test-double"

    monkeypatch.setattr("app.cli.demo.build_llm", _double)
    monkeypatch.setattr("app.agents.providers.build_llm", _double)
    monkeypatch.setattr("app.agents.providers.complete_report_with_failover", _failover)
    monkeypatch.setattr("app.agents.llm.build_llm", _double)
    assert run_demo() == 0
    output = capsys.readouterr().out
    assert "HEALTHEVIDENCE AI — EVIDENCE REVIEW DEMO" in output
    assert "Patient: PAT-000001" in output
    assert "Authorization: PA-000001" in output
    assert "Policy: POL-000001" in output
    assert "Human review required: NO" in output
    assert "DEMO COMPLETE" in output
    assert "Synthetic data: YES" in output
    assert "Autonomous clinical decision: NO" in output
    assert "Run:" in output
    assert "Agent trace:" in output
