"""Admin audit export."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import make_client


def _token(client: TestClient, *roles: str) -> str:
    response = client.post(
        "/api/v1/auth/dev-token",
        json={"subject": "audit-user", "roles": list(roles)},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_admin_can_list_audit_events(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        admin = _token(client, "admin")
        staff = _token(client, "staff")
        # Generate audit via prepare
        prep = client.post(
            "/api/v1/authorization/prepare",
            headers={"Authorization": f"Bearer {staff}"},
            json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        )
        assert prep.status_code == 200, prep.text

        forbidden = client.get(
            "/api/v1/audit/events",
            headers={"Authorization": f"Bearer {staff}"},
        )
        assert forbidden.status_code == 403

        allowed = client.get(
            "/api/v1/audit/events",
            headers={"Authorization": f"Bearer {admin}"},
            params={"limit": 50},
        )
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        assert body["total"] >= 1
        assert body["events"]
        assert "action" in body["events"][0]
        assert "detail" in body["events"][0]
        # No long clinical note dumps
        for event in body["events"]:
            assert len(event.get("detail") or "") <= 500
