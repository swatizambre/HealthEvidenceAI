"""Authorization review over the seeded synthetic cases."""

import re

from app.core.safety import DISCLAIMER
from app.services.synthetic import get_demo_procedure
from fastapi.testclient import TestClient
from tests.helpers import assert_quotes_sources, review

_DECISION = re.compile(r"\b(APPROVE|DENY|DIAGNOSE|PRESCRIBE)\b")
_PROCEDURE = get_demo_procedure()


def _criterion(body: dict[str, object], code: str) -> dict[str, object]:
    criteria = body["criteria"]
    assert isinstance(criteria, list)
    match = next(
        item for item in criteria if isinstance(item, dict) and item["criterion_id"] == code
    )
    assert isinstance(match, dict)
    return match


def test_supported_live_sample_cites_real_records(client: TestClient) -> None:
    body = review(client, "PAT-000001", case_id="PA-000001")
    assert body["human_review_required"] is False
    assert body["evidence_coverage"] == "COMPLETE"
    assert body["review_type"] == "evidence_review"
    assert body["disclaimer"] == DISCLAIMER
    assert body["missing_evidence"] == []
    assert body["run_id"]
    assert body["trace_id"]
    assert body["agent_trace"]
    criteria = body["criteria"]
    assert isinstance(criteria, list)
    assert all(isinstance(item, dict) and item["status"] == "SUPPORTED" for item in criteria)
    for item in criteria:
        assert isinstance(item, dict)
        evidence = item["evidence"]
        assert isinstance(evidence, list) and evidence
        for citation in evidence:
            assert isinstance(citation, dict)
            text = str(citation["text_reference"])
            assert text
            assert not text.startswith(("edical", "onditions", "ituation)"))
    assert_quotes_sources(client, body)


def test_missing_evidence_case(client: TestClient) -> None:
    body = review(client, "PAT-000002", case_id="PA-000002")
    assert body["human_review_required"] is True
    assert body["evidence_coverage"] == "AVAILABLE"
    assert "Required laboratory result" in body["missing_evidence"]
    assert _criterion(body, "CRIT-DYN-01")["status"] == "SUPPORTED"
    assert _criterion(body, "CRIT-DYN-02")["status"] == "SUPPORTED"
    assert _criterion(body, "CRIT-DYN-03")["status"] == "SUPPORTED"
    assert _criterion(body, "CRIT-DYN-04")["status"] == "MISSING"
    assert _criterion(body, "CRIT-DYN-05")["status"] == "UNKNOWN"
    assert_quotes_sources(client, body)


def test_not_supported_criterion(client: TestClient) -> None:
    body = review(client, "PAT-000003", case_id="PA-000003")
    item = _criterion(body, "CRIT-DYN-02")
    assert item["status"] == "NOT_SUPPORTED"
    evidence = item["evidence"]
    assert isinstance(evidence, list)
    assert evidence
    assert body["human_review_required"] is True
    assert_quotes_sources(client, body)


def test_contradiction_requires_human_review(client: TestClient) -> None:
    body = review(client, "PAT-000004", case_id="PA-000004")
    assert _criterion(body, "CRIT-DYN-02")["status"] == "UNKNOWN"
    contradictions = body["contradictions"]
    assert isinstance(contradictions, list)
    assert contradictions
    assert body["human_review_required"] is True
    assert_quotes_sources(client, body)


def test_review_has_no_autonomous_decision(client: TestClient) -> None:
    body = review(client, "PAT-000001", case_id="PA-000001")
    assert _DECISION.search(str(body)) is None
    assert "decision" not in body
    assert body["review_type"] == "evidence_review"
    assert body["awaiting_human_review"] is False


def test_review_always_awaits_senior_before_complete(client: TestClient) -> None:
    paused = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000001",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
            "case_id": "PA-000001",
        },
    )
    assert paused.status_code == 200
    body = paused.json()
    assert body["awaiting_human_review"] is True
    assert body["run_id"]


def test_validation_and_unknown_records(client: TestClient) -> None:
    invalid = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "nope",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "VALIDATION_ERROR"
    assert "Traceback" not in invalid.text
    unknown_patient = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-999999",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
        },
    )
    assert unknown_patient.status_code == 404
    assert unknown_patient.json()["error_code"] == "PATIENT_NOT_FOUND"
    unknown_policy = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000001",
            "policy_id": "POL-999999",
            "procedure": _PROCEDURE,
        },
    )
    assert unknown_policy.status_code == 404
    assert unknown_policy.json()["error_code"] == "POLICY_NOT_FOUND"
    unknown_case = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000001",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
            "case_id": "PA-999999",
        },
    )
    assert unknown_case.status_code == 404
    assert unknown_case.json()["error_code"] == "AUTHORIZATION_CASE_NOT_FOUND"
    mismatch = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000002",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
            "case_id": "PA-000001",
        },
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error_code"] == "CASE_MISMATCH"
    decision = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000001",
            "policy_id": "POL-000001",
            "procedure": "APPROVE",
        },
    )
    assert decision.status_code == 422


def test_case_list(client: TestClient) -> None:
    response = client.get("/api/v1/authorization/cases")
    assert response.status_code == 200
    cases = response.json()["cases"]
    assert len(cases) == 20
    demo = next(item for item in cases if item["case_id"] == "PA-000001")
    assert demo["patient_id"] == "PAT-000001"
    assert demo["policy_id"] == "POL-000001"
    assert demo["procedure"] == _PROCEDURE
    assert demo["status"] == "queued"


def test_review_updates_case_lifecycle(client: TestClient) -> None:
    complete = review(client, "PAT-000001", case_id="PA-000001")
    assert complete["human_review_required"] is False
    cases = client.get("/api/v1/authorization/cases").json()["cases"]
    closed = next(item for item in cases if item["case_id"] == "PA-000001")
    assert closed["status"] == "closed_as_draft"
    assert closed["last_run_id"] == complete["run_id"]

    gaps = review(client, "PAT-000002", case_id="PA-000002")
    assert gaps["human_review_required"] is True
    cases = client.get("/api/v1/authorization/cases").json()["cases"]
    needs_docs = next(item for item in cases if item["case_id"] == "PA-000002")
    assert needs_docs["status"] == "needs_documentation"


def test_interactive_human_review_resume(client: TestClient) -> None:
    paused = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000002",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
            "case_id": "PA-000002",
            "interactive": True,
        },
    )
    assert paused.status_code == 200
    body = paused.json()
    assert body["awaiting_human_review"] is True
    assert body["run_id"]
    cases = client.get("/api/v1/authorization/cases").json()["cases"]
    waiting = next(item for item in cases if item["case_id"] == "PA-000002")
    assert waiting["status"] == "ready_for_human"

    resumed = client.post(
        f"/api/v1/authorization/review/{body['run_id']}/resume",
        json={"decision": "needs_documentation", "notes": "Need recent A1c"},
    )
    assert resumed.status_code == 200
    done = resumed.json()
    assert done["awaiting_human_review"] is False
    assert done["report_summary"]
    cases = client.get("/api/v1/authorization/cases").json()["cases"]
    after = next(item for item in cases if item["case_id"] == "PA-000002")
    assert after["status"] == "needs_documentation"


def test_interactive_resume_persists_senior_assist(client: TestClient) -> None:
    paused = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000002",
            "policy_id": "POL-000001",
            "procedure": _PROCEDURE,
            "case_id": "PA-000002",
            "interactive": True,
        },
    )
    assert paused.status_code == 200
    body = paused.json()
    assert body["awaiting_human_review"] is True
    run_id = body["run_id"]

    resumed = client.post(
        f"/api/v1/authorization/review/{run_id}/resume",
        json={
            "decision": "needs_documentation",
            "notes": "Edited after AI brief",
            "senior_assist": {
                "briefing": "Senior edited briefing — verify PT notes first.",
                "focus_items": [
                    {
                        "title": "Verify PT notes",
                        "detail": "No therapy trial cited",
                        "severity": "high",
                    }
                ],
                "suggested_clinician_note": "Edited after AI brief",
                "recommended_desk_action": "needs_documentation",
                "recommended_desk_action_label": "Send back for more notes",
                "source": "template",
                "edited": True,
            },
        },
    )
    assert resumed.status_code == 200, resumed.text
    done = resumed.json()
    assert done["awaiting_human_review"] is False
    assist = done.get("senior_assist") or {}
    assert assist.get("edited") is True
    assert "Senior edited briefing" in (assist.get("briefing") or "")
    assert assist.get("focus_items")
