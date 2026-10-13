"""Phase 1 OPD patient-wise ingest."""

from typing import Any

from app.core.safety import DISCLAIMER
from fastapi.testclient import TestClient


def _packet(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "external_patient_id": "OPD-DEMO-001",
        "encounter_id": "ENC-DEMO-001",
        "note": "OPD visit. The clinical record documents Gingivitis (disorder).",
        "labs": [
            {
                "test_name": "Cholesterol in HDL [Mass/volume] in Serum or Plasma",
                "value": "55",
                "unit": "mg/dL",
            }
        ],
        "medications": [{"name": "Acetaminophen 325 MG Oral Tablet", "status": "active"}],
        "procedure": "Medication reconciliation (procedure)",
        "policy_id": "POL-000001",
        "source": "opd_manual",
        "synthetic": True,
        "consent_attested": True,
    }
    body.update(overrides)
    return body


def test_opd_ingest_creates_patient_docs_and_case(client: TestClient) -> None:
    response = client.post("/api/v1/opd/ingest", json=_packet())
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["patient_id"].startswith("PAT-")
    assert body["case_id"]
    assert body["ingest_id"]
    assert len(body["document_ids"]) >= 2
    assert body["disclaimer"] == DISCLAIMER

    patient = client.get(f"/api/v1/patients/{body['patient_id']}")
    assert patient.status_code == 200
    detail = patient.json()
    assert any("OPD_ENCOUNTER_ENC-DEMO-001" in note["content"] for note in detail["clinical_notes"])
    assert any(lab["test_name"].startswith("Cholesterol") for lab in detail["labs"])

    search = client.post(
        "/api/v1/evidence/search",
        json={"query": "OPD_ENCOUNTER_ENC-DEMO-001", "patient_id": body["patient_id"]},
    )
    assert search.status_code == 200
    assert search.json()["sources"]


def test_opd_ingest_is_idempotent_per_encounter(client: TestClient) -> None:
    first = client.post("/api/v1/opd/ingest", json=_packet()).json()
    second = client.post("/api/v1/opd/ingest", json=_packet())
    assert second.status_code == 200
    body = second.json()
    assert body["created"] is False
    assert body["patient_id"] == first["patient_id"]
    assert body["ingest_id"] == first["ingest_id"]
    assert body["case_id"] == first["case_id"]
    assert body["document_ids"] == first["document_ids"]


def test_opd_ingest_reuses_patient_across_encounters(client: TestClient) -> None:
    first = client.post("/api/v1/opd/ingest", json=_packet()).json()
    second = client.post(
        "/api/v1/opd/ingest",
        json=_packet(encounter_id="ENC-DEMO-002", note="Follow-up OPD visit note."),
    ).json()
    assert second["created"] is True
    assert second["patient_id"] == first["patient_id"]
    assert second["ingest_id"] != first["ingest_id"]
    # Same patient+policy keeps one PA case so re-check readiness stays continuous.
    assert second["case_id"] == first["case_id"]


def test_opd_ingest_reuses_existing_patient_policy_case(client: TestClient) -> None:
    prepared = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
    ).json()
    response = client.post(
        "/api/v1/opd/ingest",
        json=_packet(
            patient_id="PAT-000001",
            external_patient_id="OPD-ATTACH-001",
            encounter_id="ENC-ATTACH-001",
            note="Gap-close encounter for existing packet case.",
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["patient_id"] == "PAT-000001"
    assert body["case_id"] == prepared["case_id"]

def test_opd_ingest_rejects_non_synthetic_and_missing_consent(client: TestClient) -> None:
    denied = client.post("/api/v1/opd/ingest", json=_packet(synthetic=False))
    assert denied.status_code == 400
    assert denied.json()["error_code"] == "OPD_SYNTHETIC_REQUIRED"
    consent = client.post("/api/v1/opd/ingest", json=_packet(consent_attested=False))
    assert consent.status_code == 400
    assert consent.json()["error_code"] == "OPD_CONSENT_REQUIRED"


def test_opd_ingest_accepts_hospital_aliases(client: TestClient) -> None:
    response = client.post(
        "/api/v1/opd/ingest",
        json={
            "mrn": "UHID-9001",
            "visit_number": "OPD-VIS-9001",
            "facility_name": "City Care Hospital",
            "department": "General OPD",
            "visit_type": "outpatient",
            "attending_provider": "Dr. Rao",
            "chief_complaint": "Medication review due (situation)",
            "diagnoses": [
                {
                    "display": "Gingivitis (disorder)",
                    "code": "K05.1",
                    "code_system": "ICD-10",
                }
            ],
            "vitals": [{"name": "Heart rate", "value": "78", "unit": "/min"}],
            "labs": [],
            "medications": [],
            "procedure": "Medication reconciliation (procedure)",
            "policy_id": "POL-000001",
            "source": "his_export",
            "synthetic": True,
            "consent_attested": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["external_patient_id"] == "UHID-9001"
    assert body["encounter_id"] == "OPD-VIS-9001"
    assert body["source"] == "his_export"
    detail = client.get(f"/api/v1/patients/{body['patient_id']}").json()
    assert any("MRN/UHID: UHID-9001" in note["content"] for note in detail["clinical_notes"])
    assert any("Chief complaint:" in note["content"] for note in detail["clinical_notes"])


def test_opd_fhir_ingest_maps_bundle(client: TestClient) -> None:
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "identifier": [{"system": "urn:hospital:mrn", "value": "MRN-FHIR-1"}],
                    "name": [{"family": "Singh", "given": ["Ravi"]}],
                    "gender": "male",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "identifier": [{"value": "ENC-FHIR-1"}],
                    "class": {"code": "AMB"},
                    "reasonCode": [{"text": "Medication review due (situation)"}],
                    "serviceProvider": {"display": "Metro Hospital"},
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "code": {
                        "text": "Gingivitis (disorder)",
                        "coding": [
                            {
                                "system": "http://hl7.org/fhir/sid/icd-10",
                                "code": "K05.1",
                                "display": "Gingivitis (disorder)",
                            }
                        ],
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "code": {
                        "text": "Cholesterol in HDL [Mass/volume] in Serum or Plasma",
                        "coding": [{"system": "http://loinc.org", "code": "2085-9"}],
                    },
                    "valueQuantity": {"value": 55, "unit": "mg/dL"},
                }
            },
        ],
    }
    response = client.post(
        "/api/v1/opd/ingest/fhir",
        json={
            "bundle": bundle,
            "procedure": "Medication reconciliation (procedure)",
            "policy_id": "POL-000001",
            "synthetic": True,
            "consent_attested": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["external_patient_id"] == "MRN-FHIR-1"
    assert body["encounter_id"] == "ENC-FHIR-1"
    assert body["source"] == "fhir_r4"
    assert body["case_id"]
    detail = client.get(f"/api/v1/patients/{body['patient_id']}").json()
    assert any(lab["test_name"].startswith("Cholesterol") for lab in detail["labs"])


def test_opd_ingest_can_attach_existing_patient(client: TestClient) -> None:
    response = client.post(
        "/api/v1/opd/ingest",
        json=_packet(
            patient_id="PAT-000001",
            external_patient_id="OPD-ATTACH-001",
            encounter_id="ENC-ATTACH-001",
        ),
    )
    assert response.status_code == 201
    assert response.json()["patient_id"] == "PAT-000001"
    detail = client.get("/api/v1/patients/PAT-000001").json()
    assert any("ENC-ATTACH-001" in note["content"] for note in detail["clinical_notes"])


def test_opd_ingest_merges_multiple_diagnoses(client: TestClient) -> None:
    response = client.post(
        "/api/v1/opd/ingest",
        json={
            "mrn": "UHID-MULTI-1",
            "visit_number": "OPD-MULTI-1",
            "chief_complaint": "Follow-up for multiple chronic conditions",
            "diagnoses": [
                {"display": "Gingivitis (disorder)", "code": "K05.1", "code_system": "ICD-10"},
                {
                    "display": "Essential hypertension (disorder)",
                    "code": "I10",
                    "code_system": "ICD-10",
                },
                {"display": "Prediabetes (finding)", "code": "", "code_system": "ICD-10"},
            ],
            "labs": [],
            "medications": [],
            "procedure": "Medication reconciliation (procedure)",
            "policy_id": "POL-000001",
            "source": "his_export",
            "synthetic": True,
            "consent_attested": True,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    detail = client.get(f"/api/v1/patients/{body['patient_id']}").json()
    conditions = detail["conditions"]
    assert "Gingivitis (disorder)" in conditions
    assert "Essential hypertension (disorder)" in conditions
    # Social/admin findings are stored on ingest but hidden from clinical chart display.
    assert "Prediabetes (finding)" not in conditions
    note = " ".join(item["content"] for item in detail["clinical_notes"])
    assert "Diagnoses:" in note
    assert "Essential hypertension (disorder)" in note
    assert "Prediabetes (finding)" in note

    follow = client.post(
        "/api/v1/opd/ingest",
        json={
            "patient_id": body["patient_id"],
            "mrn": "UHID-MULTI-1",
            "visit_number": "OPD-MULTI-2",
            "chief_complaint": "Add another disorder",
            "diagnoses": [
                {"display": "Chronic sinusitis (disorder)", "code": "J32.9", "code_system": "ICD-10"}
            ],
            "labs": [],
            "medications": [],
            "procedure": "Medication reconciliation (procedure)",
            "policy_id": "POL-000001",
            "source": "his_export",
            "synthetic": True,
            "consent_attested": True,
        },
    )
    assert follow.status_code == 201, follow.text
    updated = client.get(f"/api/v1/patients/{body['patient_id']}").json()
    assert "Chronic sinusitis (disorder)" in updated["conditions"]
    assert "Gingivitis (disorder)" in updated["conditions"]


def _org(session: Any, code: str) -> str:
    from app.models import Organization
    from sqlalchemy import select

    row = session.scalar(select(Organization).where(Organization.org_code == code))
    if row is None:
        row = Organization(org_code=code, name=f"Facility {code}", facility_type="clinic", active=True)
        session.add(row)
        session.flush()
    return str(row.id)


def _ingest(session: Any, *, org_id: str | None, encounter_id: str, mrn: str) -> Any:
    from app.schemas.api import OpdIngestRequest
    from app.services.opd_ingest import ingest_opd_packet

    payload = OpdIngestRequest.model_validate(
        _packet(external_patient_id=mrn, encounter_id=encounter_id)
    )
    result = ingest_opd_packet(session, payload, org_id=org_id)
    session.commit()
    return result


def test_same_mrn_same_org_reuses_patient(client: TestClient) -> None:
    session = client.app.state.session_factory()
    try:
        org_a = _org(session, "ORG-000071")
        first = _ingest(session, org_id=org_a, encounter_id="ENC-ORG-A-1", mrn="MRN-SHARED-1")
        second = _ingest(session, org_id=org_a, encounter_id="ENC-ORG-A-2", mrn="MRN-SHARED-1")
        assert second.created is True
        assert second.patient_id == first.patient_id
    finally:
        session.close()


def test_same_mrn_different_org_never_merges(client: TestClient) -> None:
    from app.db.repository import get_patient_by_code

    session = client.app.state.session_factory()
    try:
        org_a = _org(session, "ORG-000072")
        org_b = _org(session, "ORG-000073")
        first = _ingest(session, org_id=org_a, encounter_id="ENC-X-A-1", mrn="MRN-SHARED-2")
        second = _ingest(session, org_id=org_b, encounter_id="ENC-X-B-1", mrn="MRN-SHARED-2")
        assert second.patient_id != first.patient_id
        patient_a = get_patient_by_code(session, first.patient_id)
        patient_b = get_patient_by_code(session, second.patient_id)
        assert patient_a is not None and patient_b is not None
        assert patient_a.org_id == org_a
        assert patient_b.org_id == org_b
    finally:
        session.close()


def test_org_scope_off_returning_patient_reuses_chart(client: TestClient) -> None:
    session = client.app.state.session_factory()
    try:
        first = _ingest(session, org_id=None, encounter_id="ENC-NOORG-1", mrn="MRN-NOORG-1")
        second = _ingest(session, org_id=None, encounter_id="ENC-NOORG-2", mrn="MRN-NOORG-1")
        assert second.created is True
        assert second.patient_id == first.patient_id
    finally:
        session.close()


def test_org_scope_off_reuses_legacy_unstamped_chart(client: TestClient) -> None:
    from app.db.repository import get_patient_by_code

    session = client.app.state.session_factory()
    try:
        first = _ingest(session, org_id=None, encounter_id="ENC-LEGACY-1", mrn="MRN-LEGACY-1")
        patient = get_patient_by_code(session, first.patient_id)
        assert patient is not None
        patient.org_id = None  # chart created before org stamping
        session.commit()
        second = _ingest(session, org_id=None, encounter_id="ENC-LEGACY-2", mrn="MRN-LEGACY-1")
        assert second.patient_id == first.patient_id
    finally:
        session.close()


def test_find_patient_by_external_org_matching_rules() -> None:
    from app.services.opd_ingest import _same_org

    assert _same_org("org-a", "org-a") is True
    assert _same_org("org-b", "org-a") is False
    assert _same_org(None, "org-a") is False
    assert _same_org(None, None) is True
    assert _same_org("", None) is True
    assert _same_org("org-a", None) is False
