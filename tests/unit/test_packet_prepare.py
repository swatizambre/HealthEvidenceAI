"""Evidence packet preparation for procedure readiness."""

from fastapi.testclient import TestClient


def test_prepare_packet_for_complete_patient(client: TestClient) -> None:
    response = client.post(
        "/api/v1/authorization/prepare",
        json={
            "patient_id": "PAT-000001",
            "policy_id": "POL-000001",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patient_id"] == "PAT-000001"
    assert body["case_id"].startswith("PA-")
    assert body["readiness_percent"] == 100
    assert body["gap_count"] == 0
    assert body["human_review_required"] is False
    assert body["packet_summary"]
    assert "Evidence pack" in body["packet_summary"]
    assert body["criteria"]
    assert all(item["plain_status"] for item in body["criteria"])
    assert body["next_steps"]
    assert body["next_best_action"] is None
    assert body["estimated_prep_minutes"] >= 1
    assert body["documentation_risk"] == "low"
    assert body["documentation_risk_label"]
    assert body["citation_strength"] in {"strong", "mixed", "weak"}
    assert "Not for clinical use" in body["disclaimer"] or "decision support" in body["disclaimer"].lower()


def test_prepare_packet_surfaces_gaps(client: TestClient) -> None:
    response = client.post(
        "/api/v1/authorization/prepare",
        json={
            "patient_id": "PAT-000002",
            "policy_id": "POL-000001",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["human_review_required"] is True
    assert body["gap_count"] >= 1
    assert body["readiness_percent"] < 100
    assert body["gaps"]
    assert body["gaps"][0]["action"]
    assert body["gaps"][0]["focus"]
    assert "priority" in body["gaps"][0]
    assert body["gaps"][0]["estimated_minutes"] >= 1
    assert body["gaps"][0]["specialty_hint"]
    assert body["next_best_action"] is not None
    assert body["next_best_action"]["action"]
    assert body["next_best_action"]["why"]
    assert body["estimated_prep_minutes"] >= body["next_best_action"]["estimated_minutes"]
    assert body["documentation_risk"] in {"low", "moderate", "high"}
    assert "not a denial" in body["documentation_risk_label"].lower() or "not an approval" in body[
        "documentation_risk_label"
    ].lower() or "clinician" in body["documentation_risk_label"].lower()
    assert "Staff prep estimate" in body["packet_summary"]
    assert "Next best action" in body["packet_summary"]
    # Domain-correct path: prepare must not silently close clinician HITL.
    cases = client.get("/api/v1/authorization/cases").json()["cases"]
    prepared = next(item for item in cases if item["case_id"] == body["case_id"])
    assert prepared["status"] in {"ready_for_human", "needs_documentation", "queued"}
    assert prepared["status"] != "closed_as_draft"


def test_prepare_reuses_case_when_procedure_text_changes(client: TestClient) -> None:
    first = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001", "procedure": "Procedure A"},
    )
    assert first.status_code == 200, first.text
    case_id = first.json()["case_id"]
    second = client.post(
        "/api/v1/authorization/prepare",
        json={
            "patient_id": "PAT-000001",
            "policy_id": "POL-000001",
            "procedure": "Procedure B renamed",
            "case_id": case_id,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["case_id"] == case_id