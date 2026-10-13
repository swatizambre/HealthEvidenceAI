"""Hospital interface pipeline: simulate → chart → evidence pack → status."""

from fastapi.testclient import TestClient


def test_hospital_pipeline_simulate_and_status(client: TestClient) -> None:
    status_before = client.get("/api/v1/hospital/pipeline/status")
    assert status_before.status_code == 200
    assert status_before.json()["pipeline"] == "hospital_interface"

    response = client.post(
        "/api/v1/hospital/pipeline/simulate",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001", "auto_prepare": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["patient_id"] == "PAT-000001"
    assert body["case_id"]
    assert body["encounter_id"]
    assert body["auto_prepared"] is True
    assert body["readiness_percent"] is not None
    assert body["ingest_id"]

    status = client.get("/api/v1/hospital/pipeline/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["recent_total"] >= 1
    assert payload["recent_ok"] >= 1
    assert any(run["run_id"] == body["run_id"] for run in payload["runs"])


def test_hospital_pipeline_fhir_binds_known_patient(client: TestClient) -> None:
    response = client.post(
        "/api/v1/hospital/pipeline/fhir",
        json={
            "bundle": {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "p-ed",
                            "identifier": [{"system": "urn:hospital:mrn", "value": "UHID-ED-BIND"}],
                            "name": [{"family": "Test", "given": ["ED"]}],
                            "gender": "male",
                            "birthDate": "1970-01-01",
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Encounter",
                            "id": "ed-bind",
                            "identifier": [{"value": "ED-BIND-001"}],
                            "class": {"code": "EMER"},
                            "serviceType": {"text": "Emergency"},
                            "reasonCode": [{"text": "Chest pain"}],
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Condition",
                            "code": {"text": "Chest pain (finding)"},
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Observation",
                            "category": [{"coding": [{"code": "laboratory"}]}],
                            "code": {"text": "Troponin I"},
                            "valueQuantity": {"value": 0.01, "unit": "ng/mL"},
                        }
                    },
                ],
            },
            "procedure": "Evidence pack documentation",
            "policy_id": "POL-000001",
            "patient_id": "PAT-000001",
            "synthetic": True,
            "consent_attested": True,
            "auto_prepare": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["patient_id"] == "PAT-000001"
    assert body["auto_prepared"] is True
    assert body["readiness_percent"] is not None


def test_hospital_pipeline_his_visit_without_auto_prepare(client: TestClient) -> None:
    response = client.post(
        "/api/v1/hospital/pipeline/visit",
        json={
            "external_patient_id": "UHID-PIPE-001",
            "encounter_id": "OPD-PIPE-NOAUTO-001",
            "patient_id": "PAT-000001",
            "facility_name": "North Campus OPD",
            "department": "General medicine",
            "chief_complaint": "Pipeline unit test",
            "note": "Hospital HIS webhook without auto-prepare.",
            "procedure": "Evidence pack documentation",
            "policy_id": "POL-000001",
            "source": "his_export",
            "synthetic": True,
            "consent_attested": True,
            "auto_prepare": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["auto_prepared"] is False
    assert body["patient_id"] == "PAT-000001"
    assert body["readiness_percent"] is None
