"""Pilot gate: real PostgreSQL seed + core API paths (not in-memory SQLite).

Run when Postgres is available:
  PILOT_POSTGRES_TEST=1 DATABASE_URL=postgresql+psycopg://... uv run pytest tests/pilot -v
"""

from __future__ import annotations

import os

import pytest
from tests.conftest import make_client

pytestmark = pytest.mark.skipif(
    os.environ.get("PILOT_POSTGRES_TEST") != "1",
    reason="Set PILOT_POSTGRES_TEST=1 and DATABASE_URL to a PostgreSQL instance",
)


def _pg_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url or "postgresql" not in url.lower():
        pytest.skip("DATABASE_URL must be a PostgreSQL URL for pilot tests")
    return url


def _postgres_reachable(url: str) -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OSError:
        return False
    except Exception:
        return False


def test_pilot_postgres_seed_and_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    pg = _pg_url()
    if not _postgres_reachable(pg):
        pytest.skip("PostgreSQL is not reachable at DATABASE_URL")
    with make_client(
        monkeypatch,
        database_url=pg,
        ENVIRONMENT="pilot",
        AUTH_MODE="dev-jwt",
        LLM_PROVIDER="local",
        SEED_ON_STARTUP="true",
    ) as client:
        health = client.get("/health")
        assert health.status_code == 200

        token = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "pilot-gate", "roles": ["staff"]},
        )
        assert token.status_code == 200, token.text
        headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

        patients = client.get("/api/v1/patients", headers=headers)
        assert patients.status_code == 200, patients.text
        assert patients.json()["total"] >= 1

        packet = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": "PAT-000002", "policy_id": "POL-000001"},
        )
        assert packet.status_code == 200, packet.text
        assert "readiness_percent" in packet.json()


def test_pilot_config_rejects_sqlite() -> None:
    from app.core.config import Settings
    from app.core.exceptions import AppError

    settings = Settings(
        environment="pilot",
        auth_mode="dev-jwt",
        database_url="sqlite:///./data/healthevidence.db",
        llm_provider="local",
    )
    with pytest.raises(AppError) as err:
        settings.validate_live_configuration()
    assert err.value.error_code == "LIVE_CONFIG_INVALID"
