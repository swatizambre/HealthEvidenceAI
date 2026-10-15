"""Cross-hospital safety checks: allergy conflict, same medicine twice, test not repeated."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models.entities import Document, LabResult, Medication, Patient
from app.services import safety_checks
from fastapi.testclient import TestClient
from sqlalchemy import select

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def test_generic_name_resolves_brands_and_products() -> None:
    assert safety_checks.generic_name("Glycomet 500 SR") == "metformin"
    assert safety_checks.generic_name("Augmentin 625 Duo") == "amoxicillin-clavulanate"
    assert safety_checks.generic_name("Amoxicillin 250 MG Oral Capsule") == "amoxicillin"
    assert safety_checks.generic_name("Lisinopril 10 MG Oral Tablet") == "lisinopril"
    assert safety_checks.generic_name("") == ""


def test_allergy_targets_cover_drug_family() -> None:
    targets = safety_checks._allergy_targets("Allergy to amoxicillin (rash)")
    assert targets["amoxicillin"] == "same medicine"
    assert targets["ampicillin"].startswith("same family")
    assert "metformin" not in targets
    penicillin = safety_checks._allergy_targets("Penicillin allergy")
    assert "amoxicillin" in penicillin
    sulfa = safety_checks._allergy_targets("Sulpha drug allergy")
    assert "sulfamethoxazole" in sulfa


def _seed_case(client: TestClient, patient_code: str = "PAT-000003") -> None:
    session = client.app.state.session_factory()
    try:
        patient = session.scalar(select(Patient).where(Patient.patient_code == patient_code))
        assert patient is not None
        patient.conditions = [*(patient.conditions or []), "Allergy to amoxicillin (rash, 2019)"]
        for med in session.scalars(select(Medication).where(Medication.patient_id == patient.id)).all():
            med.status = "stopped"
        document = Document(
            id=str(uuid4()),
            document_code=f"DOC-SC-{uuid4().hex[:8]}",
            patient_id=patient.id,
            document_type="lab_report",
            content="HbA1c 8.1 %",
            source="test",
        )
        session.add(document)
        session.flush()
        start = NOW - timedelta(days=200)
        session.add_all(
            [
                Medication(
                    id=str(uuid4()),
                    medication_code=f"MED-SC-{uuid4().hex[:6]}",
                    patient_id=patient.id,
                    name="Augmentin 625 Duo",
                    dose="1 tab BD",
                    status="active",
                    started_at=start,
                ),
                Medication(
                    id=str(uuid4()),
                    medication_code=f"MED-SC-{uuid4().hex[:6]}",
                    patient_id=patient.id,
                    name="Glycomet 500",
                    dose="500 mg BD",
                    status="active",
                    started_at=start,
                ),
                Medication(
                    id=str(uuid4()),
                    medication_code=f"MED-SC-{uuid4().hex[:6]}",
                    patient_id=patient.id,
                    name="Metformin 500 MG Oral Tablet",
                    dose="500 mg OD",
                    status="active",
                    started_at=start,
                ),
                Medication(
                    id=str(uuid4()),
                    medication_code=f"MED-SC-{uuid4().hex[:6]}",
                    patient_id=patient.id,
                    name="Ecosprin 75",
                    dose="75 mg OD",
                    status="stopped",
                    started_at=start,
                ),
            ]
        )
        for days_ago, value in ((400, "6.9"), (180, "8.1")):
            session.add(
                LabResult(
                    id=str(uuid4()),
                    lab_code=f"LAB-SC-{uuid4().hex[:6]}",
                    patient_id=patient.id,
                    document_id=document.id,
                    test_name="Hemoglobin A1c/Hemoglobin.total in Blood",
                    value=value,
                    unit="%",
                    collected_at=NOW - timedelta(days=days_ago),
                )
            )
        session.add(
            LabResult(
                id=str(uuid4()),
                lab_code=f"LAB-SC-{uuid4().hex[:6]}",
                patient_id=patient.id,
                document_id=document.id,
                test_name="Potassium [Moles/volume] in Serum or Plasma",
                value="6.1",
                unit="mmol/L",
                collected_at=NOW - timedelta(days=10),
            )
        )
        session.commit()
    finally:
        session.close()


def _findings(client: TestClient, patient_code: str) -> list[dict]:
    session = client.app.state.session_factory()
    try:
        return safety_checks.run_safety_checks(session, patient_code, now=NOW)["findings"]
    finally:
        session.close()


def test_safety_checks_find_all_three_kinds(client: TestClient) -> None:
    _seed_case(client)
    findings = _findings(client, "PAT-000003")
    kinds = [item["kind"] for item in findings]

    assert kinds[0] == "allergy_conflict", "high severity sorts first"
    allergy = findings[0]
    assert "amoxicillin" in allergy["doctor_text"]
    assert any(src["ref"].startswith("medication:") for src in allergy["sources"])

    duplicates = [item for item in findings if item["kind"] == "duplicate_medicine"]
    metformin = [item for item in duplicates if item["id"] == "duplicate-metformin"]
    assert metformin, duplicates
    assert len(metformin[0]["sources"]) == 2
    assert "Don't stop" in metformin[0]["patient_text"]
    assert not any("aspirin" in item["id"] for item in duplicates), "stopped medicines are ignored"

    followups = {item["id"]: item for item in findings if item["kind"] == "test_not_repeated"}
    assert "followup-hba1c" in followups
    assert "8.1" in followups["followup-hba1c"]["patient_text"]
    assert "followup-potassium" not in followups, "a recent result is still inside the follow-up window"


def test_safety_checks_api_and_doctor_brief(client: TestClient) -> None:
    _seed_case(client)
    response = client.get("/api/v1/patients/PAT-000003/safety-checks")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patient_id"] == "PAT-000003"
    assert body["checked"]["active_medicines"] >= 3
    assert body["checked"]["allergies"] >= 1
    assert "not advice" in body["disclaimer"]
    assert any(item["kind"] == "allergy_conflict" for item in body["findings"])

    brief = client.get("/api/v1/patients/PAT-000003/doctor-brief")
    assert brief.status_code == 200, brief.text
    brief_body = brief.json()
    assert brief_body["safety_findings"]
    assert "amoxicillin" in brief_body["brief_lines"][0]["text"].lower()


def test_safety_checks_quiet_record_has_no_findings(client: TestClient) -> None:
    session = client.app.state.session_factory()
    try:
        patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000004"))
        assert patient is not None
        patient.conditions = ["Hypertension"]
        for med in session.scalars(select(Medication).where(Medication.patient_id == patient.id)).all():
            session.delete(med)
        for lab in session.scalars(select(LabResult).where(LabResult.patient_id == patient.id)).all():
            session.delete(lab)
        session.commit()
    finally:
        session.close()
    assert _findings(client, "PAT-000004") == []


def test_safety_checks_unknown_patient_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/patients/PAT-999999/safety-checks")
    assert response.status_code == 404, response.text
