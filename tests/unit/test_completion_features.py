"""Completion suite: pipeline persistence, interface key, pack PDF, SLA."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import make_client


def test_hospital_pipeline_run_persisted(client: TestClient) -> None:
    run = client.post(
        "/api/v1/hospital/pipeline/simulate",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]

    status = client.get("/api/v1/hospital/pipeline/status")
    assert status.status_code == 200
    ids = [item["run_id"] for item in status.json()["runs"]]
    assert run_id in ids


def test_hospital_interface_api_key(monkeypatch) -> None:
    with make_client(
        monkeypatch,
        AUTH_MODE="dev-jwt",
        HOSPITAL_INTERFACE_API_KEY="test-hospital-key",
        HOSPITAL_ALLOW_SIMULATE="true",
    ) as client:
        blocked = client.post(
            "/api/v1/hospital/pipeline/simulate",
            json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        )
        assert blocked.status_code == 401

        ok = client.post(
            "/api/v1/hospital/pipeline/simulate",
            headers={"X-Hospital-Api-Key": "test-hospital-key"},
            json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "ok"


def test_evidence_pack_pdf_export(client: TestClient) -> None:
    response = client.get("/api/v1/authorization/cases/PA-000001/export.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content[:4] == b"%PDF"
    assert b"Evidence pack" in response.content or b"PA-000001" in response.content


def test_worklist_exposes_sla_fields(client: TestClient) -> None:
    response = client.get("/api/v1/worklist")
    assert response.status_code == 200, response.text
    body = response.json()
    cases = body.get("open_cases") or []
    assert cases
    sample = cases[0]
    assert "sla_breached" in sample
    assert sample.get("sla_minutes") is not None
