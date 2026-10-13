"""Organization / facility assignment enforcement (P2.5)."""

from __future__ import annotations

from app.models import Organization, Patient
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.conftest import make_client


def _token(
    client: TestClient,
    *roles: str,
    org_code: str | None = None,
    org_id: str | None = None,
    patient_id: str | None = None,
) -> str:
    body: dict = {"subject": "org-user", "roles": list(roles)}
    if org_code:
        body["org_code"] = org_code
    if org_id:
        body["org_id"] = org_id
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _split_patient_to_other_org(client: TestClient) -> str:
    """Move PAT-000002 to ORG-000099; return that org's UUID."""
    session = client.app.state.session_factory()
    try:
        other = session.scalar(select(Organization).where(Organization.org_code == "ORG-000099"))
        if other is None:
            other = Organization(
                org_code="ORG-000099",
                name="Other Facility",
                facility_type="clinic",
                active=True,
            )
            session.add(other)
            session.flush()
        patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000002"))
        assert patient is not None
        patient.org_id = other.id
        session.commit()
        return other.id
    finally:
        session.close()


def test_dev_token_and_me_include_org_claims(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        minted = client.post(
            "/api/v1/auth/dev-token",
            json={"subject": "alice", "roles": ["staff"], "org_code": "ORG-000001"},
        )
        assert minted.status_code == 200, minted.text
        body = minted.json()
        assert body["org_code"] == "ORG-000001"
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["org_code"] == "ORG-000001"


def test_staff_without_org_denied_when_enforced(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        token = _token(client, "staff")
        headers = {"Authorization": f"Bearer {token}"}
        listed = client.get("/api/v1/patients", headers=headers)
        assert listed.status_code == 403
        assert listed.json()["error_code"] == "ORG_SCOPE_REQUIRED"
        chart = client.get("/api/v1/patients/PAT-000001", headers=headers)
        assert chart.status_code == 403
        assert chart.json()["error_code"] == "ORG_SCOPE_REQUIRED"


def test_staff_org_code_limits_list_and_cross_org_chart(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        _split_patient_to_other_org(client)
        token = _token(client, "staff", org_code="ORG-000001")
        headers = {"Authorization": f"Bearer {token}"}

        listed = client.get("/api/v1/patients?limit=200", headers=headers)
        assert listed.status_code == 200, listed.text
        ids = {p["patient_id"] for p in listed.json()["patients"]}
        assert "PAT-000001" in ids
        assert "PAT-000002" not in ids

        own = client.get("/api/v1/patients/PAT-000001", headers=headers)
        assert own.status_code == 200, own.text
        other = client.get("/api/v1/patients/PAT-000002", headers=headers)
        assert other.status_code == 403
        assert other.json()["error_code"] == "ORG_SCOPE_FORBIDDEN"


def test_admin_without_org_cannot_list_all_patients(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        token = _token(client, "admin")
        listed = client.get(
            "/api/v1/patients?limit=200",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert listed.status_code == 403
        assert listed.json()["error_code"] == "ORG_SCOPE_REQUIRED"


def test_admin_cross_org_requires_break_glass(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        from app.services.break_glass import clear_tickets

        clear_tickets()
        _split_patient_to_other_org(client)
        token = _token(client, "admin", org_code="ORG-000001")
        headers = {"Authorization": f"Bearer {token}"}
        blocked = client.get("/api/v1/patients/PAT-000002", headers=headers)
        assert blocked.status_code == 403
        assert blocked.json()["error_code"] == "BREAK_GLASS_REQUIRED"

        ticket = client.post(
            "/api/v1/security/break-glass",
            headers=headers,
            json={
                "patient_id": "PAT-000002",
                "reason": "Emergency transfer review for patient transfer",
            },
        )
        assert ticket.status_code == 200, ticket.text
        bg = ticket.json()["break_glass_id"]
        allowed = client.get(
            "/api/v1/patients/PAT-000002",
            headers={**headers, "X-Break-Glass-Id": bg},
        )
        assert allowed.status_code == 200, allowed.text


def test_org_scope_filters_worklist_and_ops(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        _split_patient_to_other_org(client)
        token = _token(client, "staff", org_code="ORG-000001")
        headers = {"Authorization": f"Bearer {token}"}

        worklist = client.get("/api/v1/worklist", headers=headers)
        assert worklist.status_code == 200, worklist.text
        patient_ids = {p["patient_id"] for p in worklist.json()["recent_patients"]}
        assert "PAT-000002" not in patient_ids

        cases = client.get("/api/v1/authorization/cases", headers=headers)
        assert cases.status_code == 200, cases.text
        case_patients = {c["patient_id"] for c in cases.json()["cases"]}
        assert "PAT-000002" not in case_patients

        stats = client.get("/api/v1/stats", headers=headers)
        assert stats.status_code == 200, stats.text
        assert stats.json()["patients"] >= 1

        ops = client.get("/api/v1/metrics/ops", headers=headers)
        assert ops.status_code == 200, ops.text
        assert "packet_cycle" in ops.json()

        insights = client.get("/api/v1/insights", headers=headers)
        assert insights.status_code == 200, insights.text


def test_org_scope_off_keeps_full_catalog(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="false") as client:
        token = _token(client, "staff")
        headers = {"Authorization": f"Bearer {token}"}
        one = client.get("/api/v1/patients/PAT-000001", headers=headers)
        two = client.get("/api/v1/patients/PAT-000002", headers=headers)
        assert one.status_code == 200
        assert two.status_code == 200


def test_pilot_auto_enforces_org_scope_without_flag() -> None:
    """Unset ENFORCE_ORG_SCOPE → on for pilot (FAANG tenant default)."""
    from app.core.config import Settings

    auto = Settings(environment="pilot", enforce_org_scope=None)
    assert auto.org_scope_enforced() is True
    local = Settings(environment="local", enforce_org_scope=None)
    assert local.org_scope_enforced() is False
    forced_off = Settings(environment="pilot", enforce_org_scope=False)
    assert forced_off.org_scope_enforced() is False


def test_secondary_org_seeded(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="false") as client:
        token = _token(client, "admin")
        orgs = client.get(
            "/api/v1/organizations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert orgs.status_code == 200, orgs.text
        codes = {row["org_code"] for row in orgs.json()["organizations"]}
        assert "ORG-000001" in codes
        assert "ORG-000002" in codes


def test_staging_blocks_dev_token(monkeypatch) -> None:
    from app.core.config import Settings

    staging = Settings(environment="staging", auth_mode="dev-jwt")
    assert staging.dev_token_allowed() is False
    local = Settings(environment="local", auth_mode="dev-jwt")
    assert local.dev_token_allowed() is True


def test_org_scope_blocks_cross_org_prepare_and_write(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        _split_patient_to_other_org(client)
        token = _token(client, "staff", org_code="ORG-000001")
        headers = {"Authorization": f"Bearer {token}"}

        prep = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": "PAT-000002", "policy_id": "POL-000001"},
        )
        assert prep.status_code == 403
        assert prep.json()["error_code"] == "ORG_SCOPE_FORBIDDEN"

        ingest = client.post(
            "/api/v1/opd/ingest",
            headers=headers,
            json={
                "external_patient_id": "UHID-OTHER-ORG",
                "encounter_id": "OPD-ORG-SCOPE-1",
                "patient_id": "PAT-000002",
                "note": "Should not land on another org chart",
                "procedure": "Medication reconciliation (procedure)",
                "synthetic": True,
                "consent_attested": True,
                "source": "opd_manual",
            },
        )
        assert ingest.status_code == 403
        assert ingest.json()["error_code"] == "ORG_SCOPE_FORBIDDEN"
