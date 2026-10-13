"""Smoke checks for FAANG Sprint A/B trust upgrades."""

from __future__ import annotations

from app.core.config import Settings
from app.services.need_to_know import need_to_know_active
from tests.conftest import make_client


def test_auth_capabilities_public(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        response = client.get("/api/v1/auth/capabilities")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["demo_signin_allowed"] is True
        assert "enforce_org_scope" in body


def test_metrics_endpoint(monkeypatch) -> None:
    with make_client(monkeypatch) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "healthevidence_http_requests_total" in response.text


def test_need_to_know_defaults() -> None:
    assert need_to_know_active(Settings(environment="local", enforce_need_to_know=None)) is False
    assert need_to_know_active(Settings(environment="staging", enforce_need_to_know=None)) is True


def test_assign_and_case_audit(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="false") as client:
        token = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "clinician-a", "roles": ["staff"]},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        cases = client.get("/api/v1/authorization/cases", headers=headers)
        assert cases.status_code == 200, cases.text
        case_id = cases.json()["cases"][0]["case_id"]
        assigned = client.post(
            f"/api/v1/authorization/cases/{case_id}/assign",
            headers=headers,
            json={"assigned_to": "clinician-a"},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["assigned_to"] == "clinician-a"
        audit = client.get(f"/api/v1/authorization/cases/{case_id}/audit", headers=headers)
        assert audit.status_code == 200, audit.text
        actions = {row["action"] for row in audit.json()["events"]}
        assert "case_assign" in actions


def test_embedding_backend_flag() -> None:
    local = Settings(embedding_backend="dense-hash", embedding_model="dense-hash-v1")
    assert local.use_openai_embeddings() is False
    openai = Settings(embedding_backend="openai", embedding_model="text-embedding-3-small")
    assert openai.use_openai_embeddings() is True
