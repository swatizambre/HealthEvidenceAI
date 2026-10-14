"""In-process sliding-window rate limiting."""

from __future__ import annotations

import pytest
from app.api.rate_limit import SlidingWindowLimiter, rule_for_path
from app.core.config import Settings
from fastapi.testclient import TestClient
from tests.conftest import make_client


def test_sliding_window_allows_then_blocks_then_recovers() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60.0)
    assert limiter.hit("k", 2, now=0.0) == 0.0
    assert limiter.hit("k", 2, now=10.0) == 0.0
    retry = limiter.hit("k", 2, now=20.0)
    assert retry == pytest.approx(40.0)
    # Other keys are independent.
    assert limiter.hit("other", 2, now=20.0) == 0.0
    # Oldest hit leaves the window at t=60.
    assert limiter.hit("k", 2, now=61.0) == 0.0
    limiter.reset()
    assert limiter.hit("k", 1, now=61.0) == 0.0


def test_rule_groups() -> None:
    settings = Settings(
        rate_limit_auth_per_minute=7,
        rate_limit_ingest_per_minute=8,
        rate_limit_search_per_minute=9,
    )
    auth = rule_for_path("/api/v1/auth/session", settings, "POST")
    assert auth is not None and auth.group == "auth" and auth.limit == 7
    assert not auth.per_principal
    assert rule_for_path("/api/v1/auth/me", settings, "GET") is None
    opd = rule_for_path("/api/v1/opd/ingest", settings, "POST")
    assert opd is not None and opd.group == "ingest" and opd.limit == 8
    hospital = rule_for_path("/api/v1/hospital/pipeline/visit", settings, "POST")
    assert hospital is not None and hospital.group == "ingest"
    search = rule_for_path("/api/v1/evidence/search", settings, "POST")
    assert search is not None and search.group == "search" and search.limit == 9
    tools = rule_for_path("/api/v1/tools/invoke", settings, "POST")
    assert tools is not None and tools.group == "search"
    assert rule_for_path("/api/v1/patients", settings, "GET") is None


def test_rate_limit_default_off_in_test_env_only() -> None:
    assert Settings(environment="test").rate_limit_active() is False
    assert Settings(environment="test", rate_limit_enabled=True).rate_limit_active() is True
    assert Settings(environment="local").rate_limit_active() is True
    assert Settings(environment="production", rate_limit_enabled=False).rate_limit_active() is False


def test_auth_routes_return_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(
        monkeypatch,
        AUTH_MODE="dev-jwt",
        RATE_LIMIT_ENABLED="true",
        RATE_LIMIT_AUTH_PER_MINUTE="3",
    ) as client:
        body = {"subject": "rl-user", "roles": ["staff"]}
        # Demo dev-token minting is exempt (role switching must not lock the desk out).
        for _ in range(6):
            ok = client.post("/api/v1/auth/dev-token", json=body)
            assert ok.status_code == 200, ok.text
        token = client.post("/api/v1/auth/dev-token", json=body).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        # Any other POST under /auth is limited (counted before routing, after auth).
        for _ in range(3):
            assert client.post("/api/v1/auth/session", json=body, headers=headers).status_code != 429
        blocked = client.post("/api/v1/auth/session", json=body, headers=headers)
        assert blocked.status_code == 429
        payload = blocked.json()
        assert payload["error_code"] == "RATE_LIMITED"
        assert "message" in payload
        assert payload["request_id"] == blocked.headers["x-request-id"]
        assert 1 <= int(blocked.headers["retry-after"]) <= 60
        # Read-only identity probes are not part of the auth bucket.
        assert client.get("/api/v1/auth/capabilities").status_code == 200
        # Unrelated groups are unaffected.
        assert client.get("/health").status_code == 200


def test_search_limit_is_per_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(
        monkeypatch,
        AUTH_MODE="dev-jwt",
        RATE_LIMIT_ENABLED="true",
        RATE_LIMIT_SEARCH_PER_MINUTE="2",
    ) as client:

        def _headers(subject: str) -> dict[str, str]:
            minted = client.post(
                "/api/v1/auth/dev-token", json={"subject": subject, "roles": ["staff"]}
            )
            assert minted.status_code == 200, minted.text
            return {"Authorization": f"Bearer {minted.json()['access_token']}"}

        alice = _headers("alice")
        bob = _headers("bob")
        query = {"query": "hypertension follow-up", "patient_id": "PAT-000001"}
        for _ in range(2):
            assert client.post("/api/v1/evidence/search", headers=alice, json=query).status_code != 429
        assert client.post("/api/v1/evidence/search", headers=alice, json=query).status_code == 429
        # Same IP, different principal → separate bucket.
        assert client.post("/api/v1/evidence/search", headers=bob, json=query).status_code != 429


def test_rate_limit_disabled_by_default_in_tests(client: TestClient) -> None:
    for _ in range(30):
        assert client.post("/api/v1/auth/dev-token", json={"roles": ["staff"]}).status_code != 429


def test_dev_token_exempt_only_where_minting_is_allowed() -> None:
    local = Settings(environment="local", auth_mode="dev-jwt")
    assert local.dev_token_allowed()
    assert rule_for_path("/api/v1/auth/dev-token", local, "POST") is None
    pilot = Settings(environment="pilot", auth_mode="oidc")
    assert not pilot.dev_token_allowed()
    limited = rule_for_path("/api/v1/auth/dev-token", pilot, "POST")
    assert limited is not None and limited.group == "auth"
