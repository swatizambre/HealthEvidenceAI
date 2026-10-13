"""Patient medical essentials checklist."""

from fastapi.testclient import TestClient


def test_patient_essentials_scorecard(client: TestClient) -> None:
    response = client.get("/api/v1/patients/PAT-000001/essentials")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patient_id"] == "PAT-000001"
    assert 0 <= body["completeness_percent"] <= 100
    assert body["sections"]
    keys = {item["key"] for item in body["sections"]}
    assert {"conditions", "medications", "labs", "notes", "imaging", "procedures"}.issubset(keys)
    assert body["doctor_brief"]
    assert body["next_actions"]
    assert "decision support" in body["disclaimer"].lower() or "not a diagnosis" in body[
        "disclaimer"
    ].lower()


def test_help_chat_chart_grounding(client: TestClient) -> None:
    response = client.post(
        "/api/v1/help/chat",
        json={
            "message": "What essentials are missing on this chart?",
            "patient_id": "PAT-000002",
            "pathname": "/patients/PAT-000002",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"]
    assert "patient_essentials" in (body.get("context_used") or []) or "essentials" in body[
        "reply"
    ].lower() or "chart" in body["reply"].lower()
    assert any("PAT-000002" in link for link in body["suggested_links"])
