"""Security hardening: per-org hospital keys, SSE stream tickets, live secret gates."""

from __future__ import annotations

import time

import jwt
import pytest
from app.auth.middleware import AuthMiddleware, hospital_interface_principal
from app.auth.oidc import AuthPrincipal, mint_dev_jwt
from app.auth.stream_ticket import (
    STREAM_TICKET_AUDIENCE,
    issue_stream_ticket,
    verify_stream_ticket,
)
from app.core.config import Settings
from app.core.exceptions import AppError
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from tests.conftest import make_client

ORG1_KEY = "org1-interface-key-0123456789abcdefXYZ"
ORG2_KEY = "org2-interface-key-0123456789abcdefXYZ"
TICKET_SECRET = "unit-test-stream-ticket-secret-0123456789"


def _token(client: TestClient, *roles: str, org_code: str | None = None) -> str:
    body: dict = {"subject": "sec-user", "roles": list(roles)}
    if org_code:
        body["org_code"] = org_code
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _live(**overrides: str) -> Settings:
    base: dict[str, str] = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "oidc",
        "OIDC_ISSUER": "https://idp.example/realms/he",
        "OIDC_JWKS_URL": "https://idp.example/realms/he/protocol/openid-connect/certs",
        "DATABASE_URL": "postgresql+psycopg://u:p@localhost/he",
        "LLM_PROVIDER": "local",
        "SEED_ON_STARTUP": "false",
        "ENFORCE_ORG_SCOPE": "true",
        "HOSPITAL_ALLOW_SIMULATE": "false",
        "STREAM_TICKET_SECRET": TICKET_SECRET,
    }
    base.update(overrides)
    return Settings(**base)


# --- Hospital interface keys -------------------------------------------------------------


def test_per_org_key_maps_to_org_bound_principal() -> None:
    settings = Settings(hospital_interface_keys=f"ORG-000001:{ORG1_KEY}, org-000002:{ORG2_KEY}")
    first = hospital_interface_principal(ORG1_KEY, settings)
    assert first is not None
    assert first.subject == "hospital-interface:ORG-000001"
    assert first.org_code == "ORG-000001"
    second = hospital_interface_principal(ORG2_KEY, settings)
    assert second is not None
    assert second.org_code == "ORG-000002"
    assert hospital_interface_principal("wrong-key", settings) is None
    assert hospital_interface_principal("", settings) is None


def test_legacy_key_only_without_org_scope() -> None:
    legacy = "legacy-shared-interface-key-0123456789"
    off = Settings(environment="local", hospital_interface_api_key=legacy, enforce_org_scope=False)
    principal = hospital_interface_principal(legacy, off)
    assert principal is not None
    assert principal.subject == "hospital-interface"
    assert principal.org_code is None
    on = Settings(environment="local", hospital_interface_api_key=legacy, enforce_org_scope=True)
    assert hospital_interface_principal(legacy, on) is None


def test_malformed_key_entries_are_ignored() -> None:
    settings = Settings(hospital_interface_keys=f"nonsense,ORG-1:{ORG1_KEY},ORG-000003:")
    assert settings.hospital_interface_key_map() == []


def test_per_org_key_ingests_into_its_org(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(
        monkeypatch,
        AUTH_MODE="dev-jwt",
        ENFORCE_ORG_SCOPE="true",
        HOSPITAL_ALLOW_SIMULATE="true",
        HOSPITAL_INTERFACE_API_KEY="legacy-shared-interface-key-0123456789",
        HOSPITAL_INTERFACE_KEYS=f"ORG-000001:{ORG1_KEY}",
    ) as client:
        legacy = client.post(
            "/api/v1/hospital/pipeline/simulate",
            headers={"X-Hospital-Api-Key": "legacy-shared-interface-key-0123456789"},
            json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        )
        assert legacy.status_code == 401, legacy.text

        ok = client.post(
            "/api/v1/hospital/pipeline/simulate",
            headers={"X-Hospital-Api-Key": ORG1_KEY},
            json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "ok"


# --- Live configuration gates ------------------------------------------------------------


def test_live_requires_stream_ticket_secret() -> None:
    with pytest.raises(AppError) as exc:
        _live(STREAM_TICKET_SECRET="").validate_live_configuration()
    assert exc.value.error_code == "LIVE_CONFIG_INVALID"
    assert "STREAM_TICKET_SECRET" in exc.value.message
    with pytest.raises(AppError) as short:
        _live(STREAM_TICKET_SECRET="too-short").validate_live_configuration()
    assert "STREAM_TICKET_SECRET" in short.value.message


def test_pilot_requires_stream_ticket_secret() -> None:
    settings = Settings(
        ENVIRONMENT="pilot",
        AUTH_MODE="oidc",
        OIDC_ISSUER="https://idp.example/realms/he",
        OIDC_JWKS_URL="https://idp.example/realms/he/protocol/openid-connect/certs",
        DATABASE_URL="postgresql+psycopg://u:p@localhost/he",
        LLM_PROVIDER="local",
    )
    with pytest.raises(AppError) as exc:
        settings.validate_live_configuration()
    assert "STREAM_TICKET_SECRET" in exc.value.message


def test_live_rejects_legacy_interface_key_under_org_scope() -> None:
    with pytest.raises(AppError) as exc:
        _live(HOSPITAL_INTERFACE_API_KEY="x" * 40).validate_live_configuration()
    assert "HOSPITAL_INTERFACE_KEYS" in exc.value.message


def test_live_rejects_short_or_malformed_interface_keys() -> None:
    with pytest.raises(AppError) as short:
        _live(HOSPITAL_INTERFACE_KEYS="ORG-000001:short").validate_live_configuration()
    assert "32" in short.value.message
    with pytest.raises(AppError) as bad:
        _live(HOSPITAL_INTERFACE_KEYS="not-a-pair").validate_live_configuration()
    assert "ORG-NNNNNN:key" in bad.value.message
    with pytest.raises(AppError) as legacy_short:
        _live(
            ENFORCE_ORG_SCOPE="false",
            ENVIRONMENT="pilot",
            HOSPITAL_INTERFACE_API_KEY="short",
        ).validate_live_configuration()
    assert legacy_short.value.error_code == "LIVE_CONFIG_INVALID"


def test_live_accepts_strong_per_org_keys() -> None:
    keys = f"ORG-000001:{ORG1_KEY},ORG-000002:{ORG2_KEY}"
    _live(HOSPITAL_INTERFACE_KEYS=keys).validate_live_configuration()


# --- Stream tickets ----------------------------------------------------------------------


def _principal() -> AuthPrincipal:
    return AuthPrincipal(
        subject="nurse-1",
        email="nurse@example.com",
        roles=("staff",),
        raw_claims={},
        org_id="org-uuid-1",
        org_code="ORG-000001",
    )


def test_stream_ticket_round_trip_is_single_use() -> None:
    settings = Settings(environment="test", stream_ticket_secret=TICKET_SECRET)
    ticket, expires_in = issue_stream_ticket(_principal(), settings)
    assert expires_in == 60
    principal = verify_stream_ticket(ticket, settings)
    assert principal.subject == "nurse-1"
    assert principal.roles == ("staff",)
    assert principal.org_id == "org-uuid-1"
    assert principal.org_code == "ORG-000001"
    with pytest.raises(AppError) as replay:
        verify_stream_ticket(ticket, settings)
    assert replay.value.status_code == 401


def test_stream_ticket_rejects_expired_wrong_purpose_and_forged() -> None:
    settings = Settings(environment="test", stream_ticket_secret=TICKET_SECRET)
    now = int(time.time())
    base = {"sub": "x", "aud": STREAM_TICKET_AUDIENCE, "jti": "j1", "roles": ["staff"]}
    expired = jwt.encode(
        {**base, "purpose": "sse", "exp": now - 5}, TICKET_SECRET, algorithm="HS256"
    )
    wrong_purpose = jwt.encode(
        {**base, "jti": "j2", "purpose": "api", "exp": now + 30}, TICKET_SECRET, algorithm="HS256"
    )
    forged = jwt.encode(
        {**base, "jti": "j3", "purpose": "sse", "exp": now + 30},
        "attacker-secret-attacker-secret-attacker",
        algorithm="HS256",
    )
    for bad in (expired, wrong_purpose, forged, "not-a-jwt"):
        with pytest.raises(AppError) as exc:
            verify_stream_ticket(bad, settings)
        assert exc.value.error_code == "STREAM_TICKET_INVALID"


def test_stream_ticket_secret_required_outside_laptop() -> None:
    with pytest.raises(AppError) as exc:
        Settings(environment="production", stream_ticket_secret="").resolve_stream_ticket_secret()
    assert "STREAM_TICKET_SECRET" in exc.value.message
    with pytest.raises(AppError):
        Settings(environment="test", stream_ticket_secret="short").resolve_stream_ticket_secret()
    # Laptop/test desks fall back to the dev-JWT HMAC.
    assert Settings(environment="test", stream_ticket_secret="").resolve_stream_ticket_secret()


def _ticket_probe_app(settings: Settings) -> TestClient:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, settings=settings)

    @app.get("/api/v1/events/stream")
    def probe(request: Request) -> dict[str, str | None]:
        principal = request.state.principal
        return {"subject": principal.subject, "org_code": principal.org_code}

    return TestClient(app)


def test_middleware_accepts_ticket_and_rejects_access_token_query() -> None:
    settings = Settings(environment="test", auth_mode="dev-jwt", stream_ticket_secret=TICKET_SECRET)
    client = _ticket_probe_app(settings)
    ticket, _ = issue_stream_ticket(_principal(), settings)
    ok = client.get("/api/v1/events/stream", params={"ticket": ticket})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"subject": "nurse-1", "org_code": "ORG-000001"}

    replay = client.get("/api/v1/events/stream", params={"ticket": ticket})
    assert replay.status_code == 401
    assert replay.json()["error_code"] == "STREAM_TICKET_INVALID"

    bearer = mint_dev_jwt(subject="nurse-1", roles=["staff"], secret=settings.require_dev_jwt_secret())
    leaked = client.get("/api/v1/events/stream", params={"access_token": bearer})
    assert leaked.status_code == 401
    # A bearer token is not a ticket (wrong audience/purpose).
    as_ticket = client.get("/api/v1/events/stream", params={"ticket": bearer})
    assert as_ticket.status_code == 401
    header = client.get("/api/v1/events/stream", headers={"Authorization": f"Bearer {bearer}"})
    assert header.status_code == 200


def test_stream_ticket_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        anon = client.post("/api/v1/events/stream-ticket")
        assert anon.status_code == 401
        token = _token(client, "staff")
        issued = client.post(
            "/api/v1/events/stream-ticket",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert issued.status_code == 200, issued.text
        body = issued.json()
        assert body["expires_in"] == 60
        assert body["ticket"] and body["ticket"] != token
        principal = verify_stream_ticket(body["ticket"], client.app.state.settings)
        assert principal.subject == "sec-user"

        leaked = client.get("/api/v1/events/stream", params={"access_token": token})
        assert leaked.status_code == 401


def test_stream_ticket_endpoint_blocks_patient_role(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        minted = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "PAT-000001", "roles": ["patient"], "patient_id": "PAT-000001"},
        )
        token = minted.json()["access_token"]
        denied = client.post(
            "/api/v1/events/stream-ticket",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert denied.status_code == 403


def test_stream_ticket_endpoint_auth_off(client: TestClient) -> None:
    response = client.post("/api/v1/events/stream-ticket")
    assert response.status_code == 200
    assert response.json() == {"ticket": "", "expires_in": 0}
