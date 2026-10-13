"""Shared assertions for evidence reviews."""

from __future__ import annotations

from typing import Any

from app.services.synthetic import get_demo_procedure
from fastapi.testclient import TestClient

DEMO_PROCEDURE = get_demo_procedure()

# JSON response bodies from the API (values are not uniformly typed).
JsonDict = dict[str, Any]


def json_dict(response: object) -> JsonDict:
    """Parse a TestClient/HTTP response body as a JSON object."""
    payload = getattr(response, "json", lambda: None)()
    assert isinstance(payload, dict)
    return payload


def review(
    client: TestClient,
    patient_id: str,
    *,
    case_id: str | None,
    policy_id: str = "POL-000001",
    procedure: str | None = None,
    decision: str = "acknowledged",
) -> JsonDict:
    """Run review and complete mandatory senior HITL (tests simulate senior sign-off)."""
    payload: dict[str, str] = {
        "patient_id": patient_id,
        "policy_id": policy_id,
        "procedure": procedure or DEMO_PROCEDURE,
    }
    if case_id is not None:
        payload["case_id"] = case_id
    response = client.post("/api/v1/authorization/review", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    if body.get("awaiting_human_review"):
        run_id = body["run_id"]
        resumed = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            json={"decision": decision, "notes": "test senior sign-off"},
        )
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert isinstance(body, dict)
        assert body.get("awaiting_human_review") is False
    return body


def assert_quotes_sources(client: TestClient, body: JsonDict) -> None:
    criteria = body["criteria"]
    assert isinstance(criteria, list)
    for criterion in criteria:
        assert isinstance(criterion, dict)
        evidence = criterion["evidence"]
        assert isinstance(evidence, list)
        if criterion["status"] in {"SUPPORTED", "NOT_SUPPORTED"}:
            assert evidence
        if criterion["status"] == "MISSING":
            assert evidence == []
        for item in evidence:
            assert isinstance(item, dict)
            document = client.get(f"/api/v1/documents/{item['document_id']}")
            assert document.status_code == 200
            assert item["text_reference"] in document.json()["content"]
            assert item["chunk_id"]
            assert item["source"]
