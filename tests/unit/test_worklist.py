"""Clinician Today worklist."""

from fastapi.testclient import TestClient


def test_worklist_returns_recent_patients_and_open_cases(client: TestClient) -> None:
    response = client.get("/api/v1/worklist")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "recent_patients" in body
    assert "open_cases" in body
    assert len(body["recent_patients"]) >= 1
    assert len(body["open_cases"]) >= 1
    assert len(body["open_cases"]) <= 6
    assert len(body["recent_patients"]) <= 6
    patient = body["recent_patients"][0]
    assert patient["patient_id"].startswith("PAT-")
    assert "display_name" in patient
    assert "condition_summary" in patient
    assert "specialties" in patient
    case = body["open_cases"][0]
    assert case["case_id"].startswith("PA-")
    assert case["patient_id"].startswith("PAT-")
    assert case["procedure"]
    assert case["policy_title"]
    assert case["status"] in {
        "queued",
        "needs_documentation",
        "ready_for_human",
        "closed_as_draft",
    }
    assert case.get("next_hint")
    assert "policy_id" in case
    # Prefer demo / clinical procedures over catalog filler when available.
    assert not str(case["procedure"]).lower().startswith("catalog procedure")
