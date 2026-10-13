"""The loader maps a public synthetic catalog into a criteria-driven dataset."""

import re

from app.services.policy_factory import POLICY_MARKER
from app.services.synthetic import DEMO_PATIENT, build_dataset, get_demo_procedure, seed_plan

_PHONE = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def test_dataset_meets_phase1_minimums() -> None:
    data = build_dataset()
    assert len(data.patients) == 100
    assert len(data.notes) >= 100
    assert len(data.labs) >= 100
    assert len(data.medications) >= 100
    assert len(data.policies) == 20
    assert len(data.criteria) == 50
    assert len(data.imaging_studies) == 50
    assert len(data.claims) == 50
    assert len(data.cases) == 20


def test_demo_patient_includes_required_lab_from_discovered_policy() -> None:
    data = build_dataset()
    policy, _profiles, _ordered = seed_plan()
    required_lab = str(policy.criteria[3]["rule"]["test_name"])
    patient = next(item for item in data.patients if item.patient_code == DEMO_PATIENT)
    notes = [note for note in data.notes if note.patient_id == patient.id]
    labs = [lab for lab in data.labs if lab.patient_id == patient.id]
    assert notes[0].content == next(
        doc.content for doc in data.documents if doc.id == notes[0].document_id
    )
    assert "SYNTHEA_RECORD_PAT_000001" in notes[0].content
    assert "The clinical record documents" in notes[0].content
    assert any(lab.test_name == required_lab for lab in labs)
    missing = next(item for item in data.patients if item.patient_code == "PAT-000002")
    missing_labs = [lab for lab in data.labs if lab.patient_id == missing.id]
    assert all(lab.test_name != required_lab for lab in missing_labs)
    assert POLICY_MARKER in policy.content
    assert get_demo_procedure()


def test_records_do_not_carry_contact_identifiers() -> None:
    data = build_dataset()
    patients = {patient.id: patient for patient in data.patients}
    for note in data.notes:
        patient = patients[note.patient_id]
        blob = note.content
        assert _PHONE.search(blob) is None
        assert _EMAIL.search(blob) is None
        assert _SSN.search(blob) is None
        assert "@" not in blob
        assert f"SYNTHEA_RECORD_{patient.patient_code.replace('-', '_')}" in blob
    for patient in data.patients:
        assert patient.synthetic_name == f"Synthetic Patient {patient.patient_code[-6:]}"
