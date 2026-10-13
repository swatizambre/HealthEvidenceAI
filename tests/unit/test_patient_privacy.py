"""Patient record isolation and privacy controls.

Not legal advice. Planning aid for demo + production path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import make_client


def _auth_client(monkeypatch) -> TestClient:
    return make_client(monkeypatch, AUTH_MODE="dev-jwt")


def _token(client: TestClient, *roles: str, patient_id: str | None = None) -> str:
    body: dict = {"subject": "privacy-user", "roles": list(roles)}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_patient_cannot_read_another_chart(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        token = _token(client, "patient", patient_id="PAT-000001")
        headers = {"Authorization": f"Bearer {token}"}
        own = client.get("/api/v1/patients/PAT-000001", headers=headers)
        assert own.status_code == 200, own.text
        other = client.get("/api/v1/patients/PAT-000002", headers=headers)
        assert other.status_code == 403
        assert other.json()["error_code"] == "PATIENT_SCOPE_FORBIDDEN"
        lifelong = client.get("/api/v1/patients/PAT-000002/lifelong", headers=headers)
        assert lifelong.status_code == 403


def test_patient_list_is_self_only(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        token = _token(client, "patient", patient_id="PAT-000001")
        response = client.get("/api/v1/patients", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["patients"][0]["patient_id"] == "PAT-000001"


def test_patient_cannot_open_worklist(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        token = _token(client, "patient", patient_id="PAT-000001")
        response = client.get("/api/v1/worklist", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_patient_token_requires_patient_id(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        response = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "orphan", "roles": ["patient"]},
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "PATIENT_LINK_REQUIRED"


def test_staff_can_read_any_chart(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        token = _token(client, "staff")
        headers = {"Authorization": f"Bearer {token}"}
        one = client.get("/api/v1/patients/PAT-000001", headers=headers)
        two = client.get("/api/v1/patients/PAT-000002", headers=headers)
        assert one.status_code == 200
        assert two.status_code == 200


def test_patient_cannot_write_other_visit_note(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        token = _token(client, "patient", patient_id="PAT-000001")
        response = client.post(
            "/api/v1/opd/ingest",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "external_patient_id": "UHID-OTHER",
                "encounter_id": "OPD-PRIVACY-1",
                "patient_id": "PAT-000002",
                "note": "Should not land on another chart",
                "procedure": "Medication reconciliation (procedure)",
                "synthetic": True,
                "consent_attested": True,
                "source": "opd_manual",
            },
        )
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "PATIENT_SCOPE_FORBIDDEN"
