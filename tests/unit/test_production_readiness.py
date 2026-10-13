"""Readiness probe and admin break-glass."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import make_client


def test_ready_ok(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body.get("hospital_mode") in {"synthetic_practice", "production_phi", ""}


def test_break_glass_admin_only(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        staff = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "bg-staff", "roles": ["staff"]},
        ).json()["access_token"]
        admin = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "bg-admin", "roles": ["admin"]},
        ).json()["access_token"]

        forbidden = client.post(
            "/api/v1/security/break-glass",
            headers={"Authorization": f"Bearer {staff}"},
            json={
                "patient_id": "PAT-000002",
                "reason": "Need chart for after-hours review",
            },
        )
        assert forbidden.status_code == 403

        allowed = client.post(
            "/api/v1/security/break-glass",
            headers={"Authorization": f"Bearer {admin}"},
            json={
                "patient_id": "PAT-000002",
                "reason": "Need chart for after-hours PA documentation review",
            },
        )
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        assert body["patient_id"] == "PAT-000002"
        assert body["break_glass_id"]
        assert "disclaimer" in body

        events = client.get(
            "/api/v1/audit/events",
            headers={"Authorization": f"Bearer {admin}"},
            params={"action": "break_glass"},
        )
        assert events.status_code == 200, events.text
        assert events.json()["total"] >= 1
        assert any(e["action"] == "break_glass" for e in events.json()["events"])
