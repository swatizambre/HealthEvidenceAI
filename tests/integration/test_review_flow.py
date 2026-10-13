"""End-to-end evidence review without an external language model."""

from app.core.safety import DISCLAIMER
from app.services.synthetic import get_demo_procedure
from fastapi.testclient import TestClient
from tests.helpers import assert_quotes_sources, review


def test_synthetic_patient_policy_and_review(client: TestClient) -> None:
    patient = client.get("/api/v1/patients/PAT-000001")
    policy = client.get("/api/v1/policies/POL-000001")
    search = client.post(
        "/api/v1/evidence/search",
        json={
            "query": "POLICY_MARKER_DYNAMIC_REVIEW Dynamic catalog evidence review",
            "document_type": "policy",
        },
    )
    body = review(
        client,
        "PAT-000001",
        case_id="PA-000001",
        policy_id="POL-000001",
        procedure=get_demo_procedure(),
    )
    assert patient.status_code == 200
    assert policy.status_code == 200
    assert search.status_code == 200
    assert isinstance(body, dict)
    assert body["criteria"]
    assert body["disclaimer"] == DISCLAIMER
    assert "human_review_required" in body
    assert body["awaiting_human_review"] is False
    assert any(item["evidence"] for item in body["criteria"])
    assert body["missing_evidence"] == []
    assert body["run_id"]
    assert body["trace_id"]
    assert body["evidence_coverage"] == "COMPLETE"
    assert search.json()["sources"][0]["document_id"] == policy.json()["document_id"]
    assert_quotes_sources(client, body)
    assert patient.json()["clinical_notes"]
