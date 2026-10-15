"""Report upload, list, and original-file preview."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

_LAB_TXT = b"""
Patient Lab Report
HbA1c: 7.2 %
Fasting glucose: 118 mg/dL
Creatinine 1.1 mg/dL
"""


def _first_patient(client: TestClient) -> str:
    body = client.get("/api/v1/patients").json()
    assert body["patients"], "seed should create patients"
    return body["patients"][0]["patient_id"]


def test_upload_list_and_download_report(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    patient_id = _first_patient(client)
    upload = client.post(
        "/api/v1/reports/upload",
        files={"file": ("cbc.txt", _LAB_TXT, "text/plain")},
        data={"patient_id": patient_id, "document_kind": "lab_report"},
    )
    assert upload.status_code == 201, upload.text
    report = upload.json()
    assert report["patient_id"] == patient_id
    assert report["has_file"] is True
    assert report["document_id"].startswith("DOC-")
    assert report["file_url"] == f"/api/v1/documents/{report['document_id']}/file"

    listed = client.get(f"/api/v1/patients/{patient_id}/reports")
    assert listed.status_code == 200, listed.text
    reports = listed.json()["reports"]
    assert any(row["document_id"] == report["document_id"] for row in reports)

    file_resp = client.get(f"/api/v1/documents/{report['document_id']}/file")
    assert file_resp.status_code == 200, file_resp.text
    assert file_resp.content == _LAB_TXT
    assert "text/plain" in (file_resp.headers.get("content-type") or "")

    detail = client.get(f"/api/v1/documents/{report['document_id']}")
    assert detail.status_code == 200
    assert detail.json()["has_file"] is True

    chart = client.get(f"/api/v1/patients/{patient_id}")
    assert chart.status_code == 200
    labs = chart.json()["labs"]
    linked = [lab for lab in labs if lab.get("document_id") == report["document_id"]]
    assert linked
    assert linked[0]["has_file"] is True


def test_attach_file_after_ingest(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    extracted = client.post(
        "/api/v1/opd/extract",
        files={"file": ("labs.txt", _LAB_TXT, "text/plain")},
        data={"document_kind": "lab_report"},
    )
    assert extracted.status_code == 200, extracted.text
    labs = extracted.json()["labs"]
    assert labs

    ingest = client.post(
        "/api/v1/opd/ingest",
        json={
            "mrn": "UHID-REPORT-ATTACH-1",
            "visit_number": "OPD-REPORT-ATTACH-1",
            "display_name": "Report Attach Test",
            "chief_complaint": "Lab follow-up",
            "procedure": "OPD review",
            "policy_id": "POL-000001",
            "labs": [
                {
                    "test_name": row["test_name"],
                    "value": row["value"],
                    "unit": row.get("unit") or "",
                }
                for row in labs
            ],
            "medications": [],
            "synthetic": True,
            "consent_attested": True,
            "source": "opd_manual",
            "note": "Reviewed extracted labs",
        },
    )
    assert ingest.status_code in {200, 201}, ingest.text
    body = ingest.json()
    assert body["document_ids"]
    doc_id = body["document_ids"][0]

    attach = client.post(
        f"/api/v1/documents/{doc_id}/file",
        files={"file": ("labs.txt", _LAB_TXT, "text/plain")},
    )
    assert attach.status_code == 201, attach.text
    assert attach.json()["has_file"] is True

    file_resp = client.get(f"/api/v1/documents/{doc_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.content == _LAB_TXT


def test_upload_rejects_oversized_type(client: TestClient) -> None:
    patient_id = _first_patient(client)
    response = client.post(
        "/api/v1/reports/upload",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        data={"patient_id": patient_id, "document_kind": "auto"},
    )
    assert response.status_code == 422
