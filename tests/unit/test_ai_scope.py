"""AI scope and grounded gap-draft / senior-review assists."""

from __future__ import annotations

from app.core.config import Settings
from app.services.ai_assist import draft_gap_suggestion, senior_review_assist, template_gap_draft
from app.services.ai_scope import describe_ai_scope
from fastapi.testclient import TestClient


def test_ai_scope_lists_boundaries() -> None:
    scope = describe_ai_scope(Settings(CRITERIA_EVAL_MODE="ai_primary", LLM_PROVIDER="local"))
    assert scope["stance"] == "hybrid_decision_support"
    assert scope["human_in_the_loop"] is True
    assert scope["gap_drafts"] == "ai"
    assert any(item["id"] == "criteria_checklist" for item in scope["in_scope"])
    assert any(item["id"] == "senior_review" for item in scope["in_scope"])
    assert any("Approve" in item or "approve" in item.lower() for item in scope["out_of_scope"])


def test_gap_draft_template_and_ai_local() -> None:
    template = template_gap_draft("HbA1c", "labs", ["Recent lab: HbA1c 6.7%"])
    assert "HbA1c" in template
    assert "Chart cue" in template

    draft, source = draft_gap_suggestion(
        "HbA1c",
        "labs",
        ["Recent lab: HbA1c 6.7% on chart"],
        settings=Settings(CRITERIA_EVAL_MODE="ai_primary", LLM_PROVIDER="local", AI_GAP_DRAFTS="true"),
        use_llm=True,
    )
    assert draft
    assert source.startswith("ai:") or source == "template"
    assert "approv" not in draft.lower()
    assert "denial" not in draft.lower()


def test_gap_draft_rules_mode_stays_template() -> None:
    draft, source = draft_gap_suggestion(
        "Hypertension",
        "diagnoses",
        [],
        settings=Settings(CRITERIA_EVAL_MODE="rules", LLM_PROVIDER="local"),
        use_llm=True,
    )
    assert source == "template"
    assert "Hypertension" in draft
    assert "do not add a diagnosis only to satisfy" in draft.lower()
    assert "record diagnosis" not in draft.lower()


def test_ai_scope_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/ai/scope")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stance"] == "hybrid_decision_support"
    assert "in_scope" in body
    assert "out_of_scope" in body


def test_capabilities_includes_ai(client: TestClient) -> None:
    response = client.get("/api/v1/auth/capabilities")
    assert response.status_code == 200
    assert "ai" in response.json()
    assert response.json()["ai"]["human_in_the_loop"] is True


def test_gap_draft_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ai/gap-draft",
        json={
            "label": "Lipid panel",
            "focus": "labs",
            "snippets": ["LDL 118 mg/dL documented last visit"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["draft_suggestion"]
    assert body["draft_source"]
    assert "disclaimer" in body


def test_prepare_includes_ai_assist(client: TestClient) -> None:
    response = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ai_brief")
    assert isinstance(body.get("ai_assist"), dict)
    assert "scoring_path" in body["ai_assist"]


def test_senior_review_assist_template_prioritizes_gaps() -> None:
    result = senior_review_assist(
        patient_id="PAT-000001",
        case_id="PA-000001",
        procedure="Knee MRI documentation",
        criteria=[
            {
                "criterion": "Conservative therapy documented",
                "status": "MISSING",
                "reason": "No PT notes cited",
            },
            {
                "criterion": "Imaging order present",
                "status": "SUPPORTED",
                "reason": "Order on chart",
            },
        ],
        missing_evidence=["Physical therapy trial notes"],
        contradictions=["Laterality differs between note and order"],
        critic_notes=["Weak citation density on criterion 1"],
        report_summary="Pack assembled for desk review.",
        settings=Settings(CRITERIA_EVAL_MODE="rules", LLM_PROVIDER="local"),
    )
    assert result["source"] == "template"
    assert result["recommended_desk_action"] == "needs_documentation"
    assert "Senior review assist" in result["briefing"]
    assert result["focus_items"]
    assert result["focus_items"][0]["severity"] == "high"
    assert "approv" not in result["suggested_clinician_note"].lower()
    assert "denial" not in result["suggested_clinician_note"].lower()


def test_senior_review_assist_acknowledge_when_clean() -> None:
    result = senior_review_assist(
        patient_id="PAT-000002",
        case_id=None,
        procedure="Evidence pack documentation",
        criteria=[
            {"criterion": "Indication documented", "status": "SUPPORTED", "reason": "HPI cites pain"},
        ],
        missing_evidence=[],
        contradictions=[],
        critic_notes=[],
        settings=Settings(CRITERIA_EVAL_MODE="rules", LLM_PROVIDER="local"),
    )
    assert result["recommended_desk_action"] == "acknowledge_after_check"
    assert "confirmed" in result["suggested_clinician_note"].lower()


def test_senior_review_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ai/senior-review",
        json={
            "patient_id": "PAT-000001",
            "case_id": "PA-000001",
            "procedure": "Knee MRI documentation",
            "criteria": [
                {
                    "criterion": "Failed conservative care",
                    "status": "MISSING",
                    "reason": "No PT notes",
                }
            ],
            "missing_evidence": ["PT notes"],
            "contradictions": [],
            "critic_notes": [],
            "report_summary": "Desk pack ready for senior check.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["briefing"]
    assert body["focus_items"]
    assert body["suggested_clinician_note"]
    assert body["recommended_desk_action"] in {
        "needs_documentation",
        "acknowledge_after_check",
    }
    assert body["source"]
    assert "disclaimer" in body
