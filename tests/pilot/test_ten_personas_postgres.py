"""P1.10 — Ten-persona matrix against live PostgreSQL (not in-memory SQLite).

  PILOT_POSTGRES_TEST=1 DATABASE_URL=postgresql+psycopg://... uv run pytest tests/pilot -v
"""

from __future__ import annotations

import os

import pytest
from app.services.synthetic import get_demo_procedure
from tests.conftest import make_client
from tests.pilot.test_postgres_bootstrap import _pg_url, _postgres_reachable

pytestmark = pytest.mark.skipif(
    os.environ.get("PILOT_POSTGRES_TEST") != "1",
    reason="Set PILOT_POSTGRES_TEST=1 and DATABASE_URL to a PostgreSQL instance",
)

POLICY = "POL-000001"
COMPLETE = "PAT-000001"
GAPPED = "PAT-000002"
GAPPED_CASE = "PA-000002"
PROCEDURE = get_demo_procedure()


@pytest.fixture
def pg_client(monkeypatch: pytest.MonkeyPatch):
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
        yield client


def _token(
    client,
    *roles: str,
    patient_id: str | None = None,
    subject: str = "pg-persona",
    org_code: str = "ORG-000001",
) -> str:
    # Pilot env auto-enforces org scope — tokens must carry an org claim.
    body: dict = {"subject": subject, "roles": list(roles), "org_code": org_code}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
        if "patient" in roles and len(roles) == 1:
            body.pop("org_code", None)
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_pg_persona_01_staff_prepare(pg_client) -> None:
    token = _token(pg_client, "staff", subject="pg-staff-1")
    packet = pg_client.post(
        "/api/v1/authorization/prepare",
        headers=_hdr(token),
        json={"patient_id": GAPPED, "policy_id": POLICY},
    )
    assert packet.status_code == 200, packet.text
    assert "readiness_percent" in packet.json()


def test_pg_persona_02_senior_hitl(pg_client) -> None:
    senior = _token(pg_client, "senior_clinician", subject="pg-senior-2")
    headers = _hdr(senior)
    paused = pg_client.post(
        "/api/v1/authorization/review",
        headers=headers,
        json={
            "patient_id": GAPPED,
            "policy_id": POLICY,
            "procedure": PROCEDURE,
            "case_id": GAPPED_CASE,
            "interactive": True,
        },
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["awaiting_human_review"] is True
    run_id = paused.json()["run_id"]
    resumed = pg_client.post(
        f"/api/v1/authorization/review/{run_id}/resume",
        headers=headers,
        json={"decision": "needs_documentation", "notes": "pg senior"},
    )
    assert resumed.status_code == 200, resumed.text


def test_pg_persona_03_resident_resume_forbidden(pg_client) -> None:
    resident = _token(pg_client, "resident", subject="pg-resident-3")
    headers = _hdr(resident)
    assert (
        pg_client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        ).status_code
        == 200
    )
    paused = pg_client.post(
        "/api/v1/authorization/review",
        headers=headers,
        json={
            "patient_id": GAPPED,
            "policy_id": POLICY,
            "procedure": PROCEDURE,
            "case_id": GAPPED_CASE,
            "interactive": True,
        },
    )
    assert paused.status_code == 200, paused.text
    forbidden = pg_client.post(
        f"/api/v1/authorization/review/{paused.json()['run_id']}/resume",
        headers=headers,
        json={"decision": "acknowledged", "notes": "no"},
    )
    assert forbidden.status_code == 403


def test_pg_persona_04_05_patient_scope(pg_client) -> None:
    token = _token(pg_client, "patient", patient_id=COMPLETE)
    headers = _hdr(token)
    assert pg_client.get(f"/api/v1/patients/{COMPLETE}/lifelong", headers=headers).status_code == 200
    other = pg_client.get(f"/api/v1/patients/{GAPPED}", headers=headers)
    assert other.status_code == 403


def test_pg_persona_06_complete_vs_gapped(pg_client) -> None:
    token = _token(pg_client, "staff", subject="pg-staff-6")
    headers = _hdr(token)
    complete = pg_client.post(
        "/api/v1/authorization/prepare",
        headers=headers,
        json={"patient_id": COMPLETE, "policy_id": POLICY},
    )
    gapped = pg_client.post(
        "/api/v1/authorization/prepare",
        headers=headers,
        json={"patient_id": GAPPED, "policy_id": POLICY},
    )
    assert complete.status_code == 200 and gapped.status_code == 200
    assert complete.json()["readiness_percent"] >= gapped.json()["readiness_percent"]


def test_pg_persona_07_visit_note_reprepare(pg_client) -> None:
    token = _token(pg_client, "staff", subject="pg-staff-7")
    headers = _hdr(token)
    ingest = pg_client.post(
        "/api/v1/opd/ingest",
        headers=headers,
        json={
            "patient_id": GAPPED,
            "mrn": "UHID-PG-7",
            "visit_number": "OPD-PG-7",
            "encounter_id": "ENC-PG-7",
            "note": "Postgres persona visit note.",
            "labs": [],
            "medications": [],
            "procedure": "Plain X-ray of ankle region (procedure)",
            "policy_id": POLICY,
            "source": "opd_manual",
            "synthetic": True,
            "consent_attested": True,
        },
    )
    assert ingest.status_code in (200, 201), ingest.text
    packet = pg_client.post(
        "/api/v1/authorization/prepare",
        headers=headers,
        json={"patient_id": GAPPED, "policy_id": POLICY},
    )
    assert packet.status_code == 200


def test_pg_persona_08_admin_desk(pg_client) -> None:
    token = _token(pg_client, "admin", subject="pg-admin-8")
    headers = _hdr(token)
    for path in ("/api/v1/insights", "/api/v1/worklist", "/api/v1/stats", "/api/v1/audit/events"):
        assert pg_client.get(path, headers=headers).status_code == 200, path


def test_pg_persona_09_anonymous_401(pg_client) -> None:
    assert pg_client.get("/api/v1/patients").status_code == 401
    assert (
        pg_client.get("/api/v1/worklist", headers={"Authorization": "Bearer bad"}).status_code == 401
    )


def test_pg_persona_10_chart_hammer(pg_client) -> None:
    token = _token(pg_client, "staff", subject="pg-hammer-10")
    headers = _hdr(token)
    paths = [
        f"/api/v1/patients/{GAPPED}",
        f"/api/v1/patients/{GAPPED}/lifelong",
        f"/api/v1/patients/{GAPPED}/essentials",
        f"/api/v1/patients/{GAPPED}/timeline",
    ]
    for _ in range(4):
        for path in paths:
            response = pg_client.get(path, headers=headers)
            assert response.status_code == 200, path
            assert response.json().get("error_code") != "DATABASE_ERROR"
    prep = pg_client.post(
        "/api/v1/authorization/prepare",
        headers=headers,
        json={"patient_id": GAPPED, "policy_id": POLICY},
    )
    assert prep.status_code == 200
