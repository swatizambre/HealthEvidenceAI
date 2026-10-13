"""Live-ready gates: shared env, seed ban, hospital simulate, PHI synthesize forbid."""

from __future__ import annotations

import pytest
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from fastapi.testclient import TestClient
from tests.conftest import make_client


def test_ready_exposes_live_surface(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "environment" in body
    assert "hospital_mode" in body
    assert "org_scope" in body
    assert "phi_live" in body


def test_pilot_harness_rejects_allow_phi() -> None:
    settings = Settings(
        ENVIRONMENT="pilot",
        AUTH_MODE="dev-jwt",
        DEV_JWT_SECRET="ci-harness-secret-at-least-32-chars",
        DATABASE_URL="postgresql+psycopg://u:p@localhost/he",
        LLM_PROVIDER="local",
        SEED_ON_STARTUP="false",
        ALLOW_PHI="true",
        PHI_PROGRAM_ATTESTED="true",
    )
    import os

    os.environ["PILOT_POSTGRES_TEST"] = "1"
    try:
        with pytest.raises(AppError) as exc:
            settings.validate_live_configuration()
        assert exc.value.error_code == "LIVE_CONFIG_INVALID"
        assert "PILOT_POSTGRES_TEST" in exc.value.message
        assert "ALLOW_PHI" in exc.value.message
    finally:
        os.environ.pop("PILOT_POSTGRES_TEST", None)


def test_pilot_harness_requires_explicit_dev_jwt_secret() -> None:
    settings = Settings(
        ENVIRONMENT="pilot",
        AUTH_MODE="dev-jwt",
        DEV_JWT_SECRET="",
        DATABASE_URL="postgresql+psycopg://u:p@localhost/he",
        LLM_PROVIDER="local",
        ALLOW_PHI="false",
    )
    import os

    os.environ["PILOT_POSTGRES_TEST"] = "1"
    try:
        with pytest.raises(AppError) as exc:
            settings.require_dev_jwt_secret()
        assert exc.value.error_code == "AUTH_DEV_SECRET_REQUIRED"
    finally:
        os.environ.pop("PILOT_POSTGRES_TEST", None)


def test_shared_live_rejects_seed_on() -> None:
    settings = Settings(
        ENVIRONMENT="staging",
        AUTH_MODE="oidc",
        OIDC_ISSUER="https://idp.example/realms/he",
        OIDC_JWKS_URL="https://idp.example/realms/he/protocol/openid-connect/certs",
        DATABASE_URL="postgresql+psycopg://u:p@localhost/he",
        LLM_PROVIDER="local",
        SEED_ON_STARTUP="true",
        ENFORCE_ORG_SCOPE="true",
    )
    with pytest.raises(AppError) as exc:
        settings.validate_live_configuration()
    assert exc.value.error_code == "LIVE_CONFIG_INVALID"
    assert "SEED_ON_STARTUP" in exc.value.message


def test_kubernetes_requires_oidc_like_production() -> None:
    settings = Settings(
        ENVIRONMENT="kubernetes",
        AUTH_MODE="dev-jwt",
        DATABASE_URL="postgresql+psycopg://u:p@localhost/he",
        LLM_PROVIDER="local",
        SEED_ON_STARTUP="false",
        ENFORCE_ORG_SCOPE="true",
    )
    with pytest.raises(AppError) as exc:
        settings.validate_live_configuration()
    assert "oidc" in exc.value.message.lower()


def test_shared_live_ok_when_hardened() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        AUTH_MODE="oidc",
        OIDC_ISSUER="https://idp.example/realms/he",
        OIDC_JWKS_URL="https://idp.example/realms/he/protocol/openid-connect/certs",
        DATABASE_URL="postgresql+psycopg://u:p@localhost/he",
        LLM_PROVIDER="local",
        SEED_ON_STARTUP="false",
        ENFORCE_ORG_SCOPE="true",
        ALLOW_PHI="false",
        HOSPITAL_ALLOW_SIMULATE="false",
        STREAM_TICKET_SECRET="prod-stream-ticket-secret-at-least-32-chars",
    )
    settings.validate_live_configuration()
    assert settings.is_shared_live_env()
    assert settings.hospital_practice_mode()
    assert not settings.hospital_simulate_allowed()
    assert settings.org_scope_enforced()


def test_hospital_simulate_disabled_on_live_desk(monkeypatch) -> None:
    with make_client(
        monkeypatch,
        AUTH_MODE="dev-jwt",
        ENVIRONMENT="local",
        HOSPITAL_ALLOW_SIMULATE="false",
    ) as client:
        get_settings.cache_clear()
        token = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "sim-off", "roles": ["staff", "resident"]},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        status = client.get("/api/v1/hospital/pipeline/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["simulate_allowed"] is False

        blocked = client.post(
            "/api/v1/hospital/pipeline/simulate",
            headers=headers,
            json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error_code"] == "HOSPITAL_SIMULATE_DISABLED"


def test_desk_catalog_requires_auth_when_jwt_on(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENVIRONMENT="local") as client:
        get_settings.cache_clear()
        anon = client.get("/api/v1/specialties")
        assert anon.status_code == 401
        token = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "desk-staff", "roles": ["staff"]},
        ).json()["access_token"]
        ok = client.get(
            "/api/v1/specialties",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert ok.status_code == 200
        assert len(ok.json()["specialties"]) >= 8


def test_ready_reports_demo_mode_without_secrets(monkeypatch) -> None:
    secret = "demo-secret-value-that-is-long-enough-123"
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENVIRONMENT="local", DEV_JWT_SECRET=secret) as client:
        body = client.get("/ready").json()
        assert body["mode"] == "demo"
        assert body["banner"] == "DEMO — synthetic data"
        assert body["trial_site_org_code"] == ""
        assert body["trial_end_date"] == ""
        assert secret not in client.get("/ready").text
        caps = client.get("/api/v1/auth/capabilities").json()
        assert caps["deployment"]["mode"] == "demo"
    get_settings.cache_clear()


def test_deployment_banner_for_trial_and_practice() -> None:
    trial = Settings(
        ENVIRONMENT="pilot",
        ALLOW_PHI="true",
        PHI_PROGRAM_ATTESTED="true",
        TRIAL_SITE_ORG_CODE="ORG-000001",
        TRIAL_END_DATE="2026-12-31",
        DPO_CONTACT="dpo@hospital.example",
    )
    banner = trial.deployment_banner()
    assert banner["mode"] == "trial"
    assert banner["trial_site_org_code"] == "ORG-000001"
    assert banner["trial_end_date"] == "2026-12-31"
    assert banner["banner"] == "REAL-DATA TRIAL — ORG-000001 until 2026-12-31"
    assert "dpo@hospital.example" not in str(banner)

    practice = Settings(ENVIRONMENT="staging", ALLOW_PHI="false", TRIAL_SITE_ORG_CODE="ORG-000001")
    shown = practice.deployment_banner()
    assert shown["mode"] == "practice"
    assert shown["trial_site_org_code"] == ""
    assert shown["banner"].startswith("PRACTICE")
