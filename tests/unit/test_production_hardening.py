"""Production hardening: FHIR write scope, imaging RBAC, durable HITL fallback."""

from __future__ import annotations

from app.agents.checkpoints import get_checkpointer, reset_checkpointer, setup_checkpointer
from app.agents.runs import load_run
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from tests.conftest import make_client


def _token(client: TestClient, *roles: str, patient_id: str | None = None) -> str:
    body: dict = {"subject": "harden-user", "roles": list(roles)}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _fhir_bundle(*, mrn: str = "UHID-HARDEN") -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p-h",
                    "identifier": [{"system": "urn:hospital:mrn", "value": mrn}],
                    "name": [{"family": "Harden", "given": ["Test"]}],
                    "gender": "female",
                    "birthDate": "1980-01-01",
                }
            },
            {
                "resource": {
                    "resourceType": "Encounter",
                    "id": "enc-h",
                    "identifier": [{"value": "ENC-HARDEN-001"}],
                    "class": {"code": "AMB"},
                    "reasonCode": [{"text": "Follow-up"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "code": {"text": "Hypertension"},
                }
            },
        ],
    }


def test_hospital_fhir_patient_cannot_write_other_chart(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        token = _token(client, "patient", patient_id="PAT-000001")
        response = client.post(
            "/api/v1/hospital/pipeline/fhir",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "bundle": _fhir_bundle(),
                "procedure": "Evidence pack documentation",
                "policy_id": "POL-000001",
                "patient_id": "PAT-000002",
                "synthetic": True,
                "consent_attested": True,
                "auto_prepare": False,
            },
        )
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "PATIENT_SCOPE_FORBIDDEN"


def test_imaging_patient_forbidden_when_auth_on(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        patient = _token(client, "patient", patient_id="PAT-000001")
        staff = _token(client, "staff")
        denied = client.post(
            "/api/v1/imaging/analyze",
            headers={"Authorization": f"Bearer {patient}"},
            json={"study_id": "IMG-000001", "modality": "DX", "body_part": "ankle"},
        )
        assert denied.status_code == 403
        allowed = client.post(
            "/api/v1/imaging/analyze",
            headers={"Authorization": f"Bearer {staff}"},
            json={"study_id": "IMG-000001", "modality": "DX", "body_part": "ankle"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["human_review_required"] is True


def test_hitl_resume_survives_checkpointer_reset(client: TestClient) -> None:
    """Simulates multi-replica: interrupt thread gone, ReviewRun JSON still resumes."""
    paused = client.post(
        "/api/v1/authorization/review",
        json={
            "patient_id": "PAT-000002",
            "policy_id": "POL-000001",
            "procedure": "Continuous glucose monitoring",
            "case_id": "PA-000002",
            "interactive": True,
        },
    )
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["awaiting_human_review"] is True
    run_id = body["run_id"]
    assert load_run(run_id) is not None

    reset_checkpointer()
    assert get_checkpointer().get_tuple({"configurable": {"thread_id": run_id}}) is None

    resumed = client.post(
        f"/api/v1/authorization/review/{run_id}/resume",
        json={
            "decision": "needs_documentation",
            "notes": "Replica-B resume via ReviewRun",
            "senior_assist": {
                "briefing": "Cross-replica brief",
                "focus_items": [],
                "suggested_clinician_note": "Replica-B resume via ReviewRun",
                "recommended_desk_action": "needs_documentation",
                "recommended_desk_action_label": "Send back for more notes",
                "source": "template",
                "edited": True,
            },
        },
    )
    assert resumed.status_code == 200, resumed.text
    done = resumed.json()
    assert done["awaiting_human_review"] is False
    assert done["report_summary"]
    assert (done.get("senior_assist") or {}).get("edited") is True


def test_setup_checkpointer_memory_for_sqlite_memory() -> None:
    reset_checkpointer()
    saver = setup_checkpointer("sqlite://")
    assert isinstance(saver, MemorySaver)
    reset_checkpointer()
