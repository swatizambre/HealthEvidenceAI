"""AI/heuristic clinical document extraction for visit-note assist."""

from __future__ import annotations

from app.services.document_extract import extract_clinical_document
from app.services.document_text import extract_plain_text
from fastapi.testclient import TestClient

_LAB_TXT = b"""
Patient Lab Report
HbA1c: 7.2 %
Fasting glucose: 118 mg/dL
Creatinine 1.1 mg/dL
"""

_RX_TXT = b"""
Prescription
Tab. Metformin 500 mg BD
Tab. Atorvastatin 10 mg HS
"""


def test_extract_plain_text_from_bytes() -> None:
    pulled = extract_plain_text(data=_LAB_TXT, filename="labs.txt", content_type="text/plain")
    assert pulled.media_kind == "text"
    assert "HbA1c" in pulled.text


def test_heuristic_lab_extract() -> None:
    result = extract_clinical_document(
        data=_LAB_TXT,
        filename="labs.txt",
        content_type="text/plain",
        document_kind="lab_report",
    )
    assert result.extraction_method in {"heuristic", "llm"}
    names = {lab.test_name.lower() for lab in result.labs}
    assert any("hba1c" in name or "a1c" in name for name in names)
    assert any("glucose" in name for name in names)
    assert result.disclaimer


def test_heuristic_prescription_extract() -> None:
    result = extract_clinical_document(
        data=_RX_TXT,
        filename="rx.txt",
        content_type="text/plain",
        document_kind="prescription",
    )
    names = {med.name.lower() for med in result.medications}
    assert any("metformin" in name for name in names)
    assert any("atorvastatin" in name for name in names)


def test_opd_extract_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/opd/extract",
        files={"file": ("labs.txt", _LAB_TXT, "text/plain")},
        data={"document_kind": "lab_report"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["media_kind"] == "text"
    assert body["labs"]
    assert "review" in body["disclaimer"].lower()


def test_opd_extract_rejects_empty(client: TestClient) -> None:
    response = client.post(
        "/api/v1/opd/extract",
        files={"file": ("empty.txt", b"", "text/plain")},
        data={"document_kind": "auto"},
    )
    assert response.status_code == 400


def test_extract_then_ingest_updates_chart(client: TestClient) -> None:
    """Upload extract → review fields → ingest must create patient documents."""
    extracted = client.post(
        "/api/v1/opd/extract",
        files={"file": ("labs.txt", _LAB_TXT, "text/plain")},
        data={"document_kind": "lab_report"},
    )
    assert extracted.status_code == 200, extracted.text
    labs = extracted.json()["labs"]
    assert labs

    rx = client.post(
        "/api/v1/opd/extract",
        files={"file": ("rx.txt", _RX_TXT, "text/plain")},
        data={"document_kind": "prescription"},
    )
    assert rx.status_code == 200, rx.text
    meds = rx.json()["medications"]
    assert meds

    saved = client.post(
        "/api/v1/opd/ingest",
        json={
            "mrn": "UHID-EXTRACT-UI-1",
            "visit_number": "OPD-EXTRACT-UI-1",
            "chief_complaint": "Lab and prescription follow-up",
            "labs": labs,
            "medications": meds,
            "procedure": "Evidence pack documentation",
            "policy_id": "POL-000001",
            "source": "opd_manual",
            "synthetic": True,
            "consent_attested": True,
            "note": extracted.json().get("note") or "Reviewed extracted fields",
        },
    )
    assert saved.status_code in {200, 201}, saved.text
    body = saved.json()
    assert body["patient_id"].startswith("PAT-")
    assert body["document_ids"]
    assert body["case_id"]
