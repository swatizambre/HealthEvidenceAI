"""Ops metrics, organizations, and PHI production gates."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.core.exceptions import AppError
from fastapi.testclient import TestClient


def test_ops_metrics_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/metrics/ops")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "packet_cycle" in body
    cycle = body["packet_cycle"]
    assert cycle["unit"] == "minutes"
    assert "sample_size" in cycle
    assert body["allow_phi"] is False
    assert "organization_count" in body
    assert body["disclaimer"]


def test_organizations_list(client: TestClient) -> None:
    response = client.get("/api/v1/organizations")
    assert response.status_code == 200, response.text
    orgs = response.json()["organizations"]
    assert orgs
    assert orgs[0]["org_code"].startswith("ORG-")
    assert orgs[0]["name"]


def test_prepare_includes_cycle_elapsed(client: TestClient) -> None:
    response = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "cycle_elapsed_minutes" in body
    assert body["cycle_elapsed_minutes"] is None or body["cycle_elapsed_minutes"] >= 0


def test_production_blocks_phi_without_attestation() -> None:
    settings = Settings(
        environment="production",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_jwks_url="https://issuer.example/jwks",
        database_url="postgresql+psycopg://u:p@localhost/db",
        llm_provider="local",
        allow_phi=True,
        phi_program_attested=False,
    )
    with pytest.raises(AppError) as err:
        settings.validate_live_configuration()
    assert err.value.error_code == "LIVE_CONFIG_INVALID"
