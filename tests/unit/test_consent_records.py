"""Stored consent records and consent enforcement on OPD ingest (DPDP / HIPAA trail)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models import ConsentRecord, Patient
from app.schemas.api import ConsentCreate
from app.services.consent import (
    PRACTICE_NOTICE_VERSION,
    active_consent,
    is_consent_active,
    record_consent,
    require_ingest_consent,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.conftest import make_client

PHI_ENV = {"ALLOW_PHI": "true", "PHI_PROGRAM_ATTESTED": "true"}


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    # PHI-mode clients must not leak cached settings into later tests.
    yield
    get_settings.cache_clear()


def _packet(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "external_patient_id": "UHID-CONSENT-1",
        "encounter_id": "ENC-CONSENT-1",
        "note": "OPD visit. The clinical record documents Gingivitis (disorder).",
        "labs": [],
        "medications": [],
        "procedure": "Medication reconciliation (procedure)",
        "policy_id": "POL-000001",
        "source": "opd_manual",
        "synthetic": False,
        "consent_attested": False,
    }
    body.update(overrides)
    return body


def _consent(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "purpose": "prior_auth_evidence",
        "method": "written",
        "language": "hi",
        "notice_version": "notice-2026-10",
        "granted_by_name": "Asha Patel",
        "scope": "OPD notes, labs, and prior-auth evidence packs at this facility.",
        "evidence_ref": "DOC-SCAN-0001",
    }
    body.update(overrides)
    return body


def _fhir_bundle(mrn: str, encounter: str) -> dict[str, object]:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": [{"system": "urn:hospital:mrn", "value": mrn}],
                    "name": [{"family": "Singh", "given": ["Ravi"]}],
                    "gender": "male",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "identifier": [{"value": encounter}],
                    "class": {"code": "AMB"},
                    "reasonCode": [{"text": "Medication review due (situation)"}],
                }
            },
            {"resource": {"resourceType": "Condition", "code": {"text": "Gingivitis (disorder)"}}},
        ],
    }


# --- Practice / synthetic mode ----------------------------------------------------------


def test_practice_ingest_stores_consent_record(client: TestClient) -> None:
    response = client.post(
        "/api/v1/opd/ingest",
        json=_packet(synthetic=True, consent_attested=True),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["consent_id"].startswith("CNS-")

    listed = client.get(f"/api/v1/patients/{body['patient_id']}/consents")
    assert listed.status_code == 200, listed.text
    consents = listed.json()["consents"]
    assert len(consents) == 1
    assert consents[0]["consent_id"] == body["consent_id"]
    assert consents[0]["method"] == "electronic"
    assert consents[0]["notice_version"] == PRACTICE_NOTICE_VERSION
    assert consents[0]["active"] is True

    # Second visit reuses the same practice consent instead of piling up rows.
    again = client.post(
        "/api/v1/opd/ingest",
        json=_packet(encounter_id="ENC-CONSENT-2", synthetic=True, consent_attested=True),
    )
    assert again.status_code == 201, again.text
    assert again.json()["consent_id"] == body["consent_id"]
    # Idempotent replay reports the stored consent too.
    replay = client.post(
        "/api/v1/opd/ingest",
        json=_packet(synthetic=True, consent_attested=True),
    )
    assert replay.status_code == 200
    assert replay.json()["consent_id"] == body["consent_id"]


def test_practice_mode_still_rejects_missing_attestation(client: TestClient) -> None:
    response = client.post("/api/v1/opd/ingest", json=_packet(synthetic=True))
    assert response.status_code == 400
    assert response.json()["error_code"] == "OPD_CONSENT_REQUIRED"


def test_practice_mode_accepts_stored_consent_id(client: TestClient) -> None:
    created = client.post("/api/v1/patients/PAT-000001/consents", json=_consent())
    assert created.status_code == 201, created.text
    code = created.json()["consent_id"]
    response = client.post(
        "/api/v1/opd/ingest",
        json=_packet(patient_id="PAT-000001", synthetic=True, consent_id=code),
    )
    assert response.status_code == 201, response.text
    assert response.json()["consent_id"] == code


# --- PHI mode enforcement -----------------------------------------------------------------


def test_phi_ingest_requires_consent(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        bare = client.post("/api/v1/opd/ingest", json=_packet(consent_attested=True))
        assert bare.status_code == 403, bare.text
        assert bare.json()["error_code"] == "CONSENT_REQUIRED"

        fhir = client.post(
            "/api/v1/opd/ingest/fhir",
            json={
                "bundle": _fhir_bundle("MRN-PHI-1", "ENC-PHI-FHIR-1"),
                "synthetic": False,
                "consent_attested": True,
            },
        )
        assert fhir.status_code == 403, fhir.text
        assert fhir.json()["error_code"] == "CONSENT_REQUIRED"


def test_phi_inline_consent_creates_patient_and_consent(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        response = client.post("/api/v1/opd/ingest", json=_packet(consent=_consent()))
        assert response.status_code == 201, response.text
        body = response.json()
        consents = client.get(f"/api/v1/patients/{body['patient_id']}/consents").json()
        assert consents["total"] == 1
        stored = consents["consents"][0]
        assert stored["consent_id"] == body["consent_id"]
        assert stored["method"] == "written"
        assert stored["granted_by_name"] == "Asha Patel"
        assert stored["evidence_ref"] == "DOC-SCAN-0001"


def test_phi_inline_consent_rejected_for_existing_chart(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        response = client.post(
            "/api/v1/opd/ingest",
            json=_packet(patient_id="PAT-000001", consent=_consent()),
        )
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "CONSENT_REQUIRED"
        # Nothing was stored: the transaction rolled back.
        assert client.get("/api/v1/patients/PAT-000001/consents").json()["total"] == 0


def test_phi_inline_consent_with_non_ingest_purpose_rejected(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        response = client.post(
            "/api/v1/opd/ingest",
            json=_packet(consent=_consent(purpose="research_trial")),
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "CONSENT_REQUIRED"


def test_phi_ingest_with_stored_consent_then_revoked(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        created = client.post("/api/v1/patients/PAT-000001/consents", json=_consent())
        assert created.status_code == 201, created.text
        code = created.json()["consent_id"]
        assert code.startswith("CNS-")

        ok = client.post(
            "/api/v1/opd/ingest",
            json=_packet(patient_id="PAT-000001", consent_id=code),
        )
        assert ok.status_code == 201, ok.text
        assert ok.json()["consent_id"] == code

        fhir = client.post(
            "/api/v1/opd/ingest/fhir",
            json={
                "bundle": _fhir_bundle("MRN-PHI-2", "ENC-PHI-FHIR-2"),
                "patient_id": "PAT-000001",
                "synthetic": False,
                "consent_id": code,
            },
        )
        assert fhir.status_code == 201, fhir.text

        revoked = client.post(
            f"/api/v1/patients/PAT-000001/consents/{code}/revoke",
            json={"reason": "Patient withdrew at front desk"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["active"] is False
        assert revoked.json()["revoked_reason"] == "Patient withdrew at front desk"

        blocked = client.post(
            "/api/v1/opd/ingest",
            json=_packet(
                patient_id="PAT-000001", encounter_id="ENC-AFTER-REVOKE", consent_id=code
            ),
        )
        assert blocked.status_code == 403, blocked.text
        assert blocked.json()["error_code"] == "CONSENT_REQUIRED"
        assert "withdrawn" in blocked.json()["message"]

        again = client.post(
            f"/api/v1/patients/PAT-000001/consents/{code}/revoke",
            json={"reason": "double click"},
        )
        assert again.status_code == 409
        assert again.json()["error_code"] == "CONSENT_ALREADY_REVOKED"


def test_phi_consent_must_match_patient_and_purpose(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        other = client.post("/api/v1/patients/PAT-000002/consents", json=_consent()).json()
        wrong_patient = client.post(
            "/api/v1/opd/ingest",
            json=_packet(patient_id="PAT-000001", consent_id=other["consent_id"]),
        )
        assert wrong_patient.status_code == 403
        assert wrong_patient.json()["error_code"] == "CONSENT_REQUIRED"

        research = client.post(
            "/api/v1/patients/PAT-000001/consents",
            json=_consent(purpose="research_trial"),
        ).json()
        wrong_purpose = client.post(
            "/api/v1/opd/ingest",
            json=_packet(patient_id="PAT-000001", consent_id=research["consent_id"]),
        )
        assert wrong_purpose.status_code == 403
        assert "research_trial" in wrong_purpose.json()["message"]

        continuity = client.post(
            "/api/v1/patients/PAT-000001/consents",
            json=_consent(purpose="continuity_of_care", method="verbal_witnessed"),
        ).json()
        ok = client.post(
            "/api/v1/opd/ingest",
            json=_packet(patient_id="PAT-000001", consent_id=continuity["consent_id"]),
        )
        assert ok.status_code == 201, ok.text


def test_capabilities_report_consent_mode(monkeypatch) -> None:
    with make_client(monkeypatch, **PHI_ENV) as client:
        body = client.get("/api/v1/auth/capabilities").json()
        assert body["phi_live"] is True
        assert body["consent_mode"] == "stored_required"
    with make_client(monkeypatch, ALLOW_PHI="false", PHI_PROGRAM_ATTESTED="false") as client:
        body = client.get("/api/v1/auth/capabilities").json()
        assert body["phi_live"] is False
        assert body["consent_mode"] == "attestation"


# --- Consent API validation + RBAC --------------------------------------------------------


def test_consent_validation_errors(client: TestClient) -> None:
    now = datetime.now(UTC)
    bad_expiry = client.post(
        "/api/v1/patients/PAT-000001/consents",
        json=_consent(
            granted_at=now.isoformat(), expires_at=(now - timedelta(days=1)).isoformat()
        ),
    )
    assert bad_expiry.status_code == 422
    assert bad_expiry.json()["error_code"] == "CONSENT_INVALID"
    future = client.post(
        "/api/v1/patients/PAT-000001/consents",
        json=_consent(granted_at=(now + timedelta(days=2)).isoformat()),
    )
    assert future.status_code == 422
    bad_method = client.post(
        "/api/v1/patients/PAT-000001/consents", json=_consent(method="telepathy")
    )
    assert bad_method.status_code == 422
    missing = client.post(
        "/api/v1/patients/PAT-000001/consents/CNS-999999/revoke",
        json={"reason": "not mine"},
    )
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "CONSENT_NOT_FOUND"


def _token(client: TestClient, *roles: str, patient_id: str | None = None) -> str:
    body: dict[str, object] = {"subject": "nurse.priya@hospital.example", "roles": list(roles)}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_patient_self_consent_list_and_revoke(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        staff = {"Authorization": f"Bearer {_token(client, 'staff')}"}
        patient = {"Authorization": f"Bearer {_token(client, 'patient', patient_id='PAT-000001')}"}

        created = client.post(
            "/api/v1/patients/PAT-000001/consents", headers=staff, json=_consent()
        )
        assert created.status_code == 201, created.text
        code = created.json()["consent_id"]
        assert created.json()["recorded_by"] == "nurse.priya@hospital.example"

        # Patients cannot self-record consent (desk act) …
        self_record = client.post(
            "/api/v1/patients/PAT-000001/consents", headers=patient, json=_consent()
        )
        assert self_record.status_code == 403
        # … but can list and withdraw their own.
        own = client.get("/api/v1/patients/PAT-000001/consents", headers=patient)
        assert own.status_code == 200
        assert own.json()["consents"][0]["consent_id"] == code
        # Patient view masks the recording staff member's personal identifier.
        assert "nurse.priya@hospital.example" not in own.text
        assert own.json()["consents"][0]["recorded_by"].startswith("Care team")
        other = client.get("/api/v1/patients/PAT-000002/consents", headers=patient)
        assert other.status_code == 403
        assert other.json()["error_code"] == "PATIENT_SCOPE_FORBIDDEN"

        revoke = client.post(
            f"/api/v1/patients/PAT-000001/consents/{code}/revoke",
            headers=patient,
            json={"reason": "I no longer want this"},
        )
        assert revoke.status_code == 200, revoke.text
        assert revoke.json()["revoked_at"]


# --- Service-level helpers ---------------------------------------------------------------


def test_active_consent_helper_respects_expiry_org_and_revocation(monkeypatch) -> None:
    with make_client(monkeypatch) as client:
        session = client.app.state.session_factory()
        try:
            patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000003"))
            assert patient is not None
            now = datetime.now(UTC)
            assert active_consent(session, patient.id, "prior_auth_evidence") is None
            short = record_consent(
                session,
                patient,
                ConsentCreate(
                    method="electronic",
                    notice_version="v1",
                    granted_by_name="Self",
                    granted_at=now - timedelta(days=10),
                    expires_at=now - timedelta(days=1),
                ),
                recorded_by="tester",
            )
            assert not is_consent_active(short)
            assert active_consent(session, patient.id, "prior_auth_evidence") is None
            with pytest.raises(AppError) as exc:
                require_ingest_consent(session, patient, short.consent_code)
            assert exc.value.error_code == "CONSENT_REQUIRED"

            current = record_consent(
                session,
                patient,
                ConsentCreate(method="written", notice_version="v2", granted_by_name="Self"),
                recorded_by="tester",
                org_id=patient.org_id,
            )
            found = active_consent(session, patient.id, "prior_auth_evidence", patient.org_id)
            assert found is not None and found.consent_code == current.consent_code
            assert active_consent(session, patient.id, "continuity_of_care") is None
            # Different facility does not inherit this facility's consent.
            assert (
                active_consent(session, patient.id, "prior_auth_evidence", "other-org-id") is None
            )
            with pytest.raises(AppError):
                require_ingest_consent(
                    session, patient, current.consent_code, org_id="other-org-id"
                )
            stored = session.scalar(
                select(ConsentRecord).where(ConsentRecord.consent_code == current.consent_code)
            )
            assert stored is not None and stored.revoked_at is None
        finally:
            session.rollback()
            session.close()


def test_consent_migration_upgrade_and_downgrade(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from app.db.base import Base
    from sqlalchemy import create_engine, inspect

    db_url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    engine = create_engine(db_url)
    from app import models  # noqa: F401

    base_tables = [
        table
        for name, table in Base.metadata.tables.items()
        if name not in {"consent_records", "data_subject_requests", "hospital_pipeline_runs"}
    ]
    Base.metadata.create_all(bind=engine, tables=base_tables)
    root = Path(__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    try:
        command.upgrade(cfg, "head")
        names = set(inspect(engine).get_table_names())
        assert {"consent_records", "data_subject_requests"} <= names
        command.downgrade(cfg, "20261009_0002")
        names = set(inspect(engine).get_table_names())
        assert "consent_records" not in names
        assert "data_subject_requests" not in names
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_phi_ingest_blocked_after_trial_end(monkeypatch) -> None:
    with make_client(monkeypatch, TRIAL_END_DATE="2000-01-01", **PHI_ENV) as client:
        response = client.post("/api/v1/opd/ingest", json=_packet(consent=_consent()))
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "TRIAL_ENDED"
