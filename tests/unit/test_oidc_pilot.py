"""OIDC role extraction and configuration status for pilot."""

from __future__ import annotations

from app.auth.oidc import extract_roles, oidc_configuration_status
from app.auth.rbac import normalize_roles
from app.core.config import Settings
from tests.conftest import make_client


def test_extract_roles_keycloak_shapes() -> None:
    settings = Settings(oidc_roles_claim="roles", oidc_client_id="healthevidence-api")
    claims = {
        "roles": ["staff"],
        "realm_access": {"roles": ["senior_clinician", "offline_access"]},
        "resource_access": {
            "healthevidence-api": {"roles": ["admin"]},
            "account": {"roles": ["manage-account"]},
        },
    }
    roles = extract_roles(claims, settings)
    assert "staff" in roles
    assert "senior_clinician" in roles
    assert "admin" in roles
    product = normalize_roles(roles)
    assert "staff" in product
    assert "senior_clinician" in product
    assert "admin" in product


def test_oidc_status_dev_jwt(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        response = client.get("/api/v1/auth/oidc/status")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["auth_mode"] == "dev-jwt"
        assert body["oidc_ready"] is False
        assert "detail" in body


def test_oidc_status_reports_ready_when_configured() -> None:
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer="https://idp.example/realms/he",
        oidc_jwks_url="https://idp.example/realms/he/protocol/openid-connect/certs",
        oidc_audience="healthevidence-api",
        oidc_client_id="healthevidence-api",
    )
    status = oidc_configuration_status(settings)
    assert status["oidc_ready"] is True
    assert status["issuer_configured"] is True
    assert status["jwks_configured"] is True


def test_discover_oidc_endpoints(monkeypatch) -> None:
    from app.auth.oidc import discover_oidc_endpoints

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "issuer": "https://idp.example/realms/he",
                "jwks_uri": "https://idp.example/realms/he/protocol/openid-connect/certs",
                "token_endpoint": "https://idp.example/token",
            }

    monkeypatch.setattr("app.auth.oidc.httpx.get", lambda *a, **k: _Resp())
    endpoints = discover_oidc_endpoints("https://idp.example/realms/he")
    assert endpoints["jwks_url"].endswith("/certs")
    assert endpoints["issuer"].endswith("/realms/he")


def test_dev_token_disabled_under_oidc_mode(monkeypatch) -> None:
    with make_client(
        monkeypatch,
        AUTH_MODE="oidc",
        ENVIRONMENT="local",
        OIDC_ISSUER="https://idp.example",
        OIDC_JWKS_URL="https://idp.example/jwks",
        DATABASE_URL="sqlite://",
        LLM_PROVIDER="local",
    ) as client:
        response = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "x", "roles": ["staff"]},
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "AUTH_DEV_TOKEN_DISABLED"
