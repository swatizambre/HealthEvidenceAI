"""RBAC: senior clinician vs staff desk roles."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.conftest import make_client


def _auth_client(monkeypatch) -> TestClient:
    return make_client(monkeypatch, AUTH_MODE="dev-jwt")


def _token(client: TestClient, *roles: str) -> str:
    response = client.post(
        "/api/v1/auth/dev-token",
        json={"subject": "rbac-user", "roles": list(roles)},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_staff_cannot_resume_hitl(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        senior = _token(client, "senior_clinician")
        staff = _token(client, "staff")
        paused = client.post(
            "/api/v1/authorization/review",
            headers={"Authorization": f"Bearer {senior}"},
            json={
                "patient_id": "PAT-000002",
                "policy_id": "POL-000001",
                "procedure": "Continuous glucose monitoring",
                "case_id": "PA-000002",
                "interactive": True,
            },
        )
        assert paused.status_code == 200, paused.text
        run_id = paused.json()["run_id"]
        assert paused.json()["awaiting_human_review"] is True

        forbidden = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            headers={"Authorization": f"Bearer {staff}"},
            json={"decision": "acknowledged", "notes": "staff attempt"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error_code"] == "RBAC_FORBIDDEN"

        allowed = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            headers={"Authorization": f"Bearer {senior}"},
            json={"decision": "needs_documentation", "notes": "Need labs"},
        )
        assert allowed.status_code == 200, allowed.text


def test_staff_can_prepare_packet(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        staff = _token(client, "staff")
        response = client.post(
            "/api/v1/authorization/prepare",
            headers={"Authorization": f"Bearer {staff}"},
            json={
                "patient_id": "PAT-000001",
                "policy_id": "POL-000001",
            },
        )
        assert response.status_code == 200, response.text
        assert "readiness_percent" in response.json()


def test_resident_can_check_evidence_but_not_resume(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        resident = _token(client, "resident")
        paused = client.post(
            "/api/v1/authorization/review",
            headers={"Authorization": f"Bearer {resident}"},
            json={
                "patient_id": "PAT-000002",
                "policy_id": "POL-000001",
                "procedure": "Continuous glucose monitoring",
                "case_id": "PA-000002",
                "interactive": True,
            },
        )
        assert paused.status_code == 200, paused.text
        run_id = paused.json()["run_id"]
        forbidden = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            headers={"Authorization": f"Bearer {resident}"},
            json={"decision": "acknowledged", "notes": "resident attempt"},
        )
        assert forbidden.status_code == 403


def test_admin_cannot_acknowledge_without_senior_role(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        senior = _token(client, "senior_clinician")
        admin = _token(client, "admin")
        paused = client.post(
            "/api/v1/authorization/review",
            headers={"Authorization": f"Bearer {senior}"},
            json={
                "patient_id": "PAT-000002",
                "policy_id": "POL-000001",
                "procedure": "Continuous glucose monitoring",
                "case_id": "PA-000002",
                "interactive": True,
            },
        )
        assert paused.status_code == 200, paused.text
        run_id = paused.json()["run_id"]
        forbidden = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            headers={"Authorization": f"Bearer {admin}"},
            json={"decision": "acknowledged", "notes": "admin attempt"},
        )
        assert forbidden.status_code == 403


def test_staff_cannot_ack_via_tools_invoke(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        staff = _token(client, "staff")
        forged = client.post(
            "/api/v1/tools/invoke",
            headers={"Authorization": f"Bearer {staff}"},
            json={
                "tool_name": "create_human_review",
                "agent": "AuthorizationAgent",
                "arguments": {
                    "run_id": "RUN-FORGED",
                    "patient_id": "PAT-000001",
                    "reason": "staff forging acknowledgment",
                    "decision": "acknowledged",
                },
            },
        )
        assert forged.status_code == 403
        assert forged.json()["error_code"] == "RBAC_FORBIDDEN"


def test_resident_cannot_ack_via_tools_invoke(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        resident = _token(client, "resident")
        forged = client.post(
            "/api/v1/tools/invoke",
            headers={"Authorization": f"Bearer {resident}"},
            json={
                "tool_name": "create_human_review",
                "agent": "AuthorizationAgent",
                "arguments": {
                    "run_id": "RUN-FORGED",
                    "patient_id": "PAT-000001",
                    "reason": "resident forging acknowledgment",
                    "decision": "acknowledged",
                },
            },
        )
        assert forged.status_code == 403


def test_dev_token_normalizes_reviewer_to_senior(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        response = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "legacy", "roles": ["reviewer"]},
        )
        assert response.status_code == 200
        assert "senior_clinician" in response.json()["roles"]
