"""Patient rights self-service: access log, export, and data-subject requests."""

from __future__ import annotations

from datetime import datetime

from app.services.patient_rights import action_label, classify_actor, staff_reference
from fastapi.testclient import TestClient
from tests.conftest import make_client

STAFF_EMAIL = "dr.meera.private@hospital.example"


def _token(
    client: TestClient,
    *roles: str,
    patient_id: str | None = None,
    subject: str = STAFF_EMAIL,
    org_code: str | None = None,
) -> dict[str, str]:
    body: dict[str, object] = {"subject": subject, "roles": list(roles)}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    if org_code:
        body["org_code"] = org_code
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _auth_client(monkeypatch) -> TestClient:
    return make_client(monkeypatch, AUTH_MODE="dev-jwt")


def test_access_log_lists_staff_opens_without_leaking_email(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        staff = _token(client, "staff")
        me = _token(client, "patient", patient_id="PAT-000001")
        other_patient = _token(client, "patient", patient_id="PAT-000002")

        assert client.get("/api/v1/patients/PAT-000001", headers=staff).status_code == 200
        assert client.get("/api/v1/patients/PAT-000002", headers=staff).status_code == 200
        # A blocked attempt by another patient must show as denied.
        assert client.get("/api/v1/patients/PAT-000001", headers=other_patient).status_code == 403

        response = client.get("/api/v1/me/access-log", headers=me)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["patient_id"] == "PAT-000001"
        assert body["total"] >= 2
        assert STAFF_EMAIL not in response.text
        entries = body["entries"]
        # Newest first.
        stamps = [
            datetime.fromisoformat(entry["occurred_at"].replace("Z", "+00:00")) for entry in entries
        ]
        assert stamps == sorted(stamps, reverse=True)
        staff_rows = [entry for entry in entries if entry["actor_category"] == "care_team"]
        assert staff_rows
        assert staff_rows[0]["action_label"] == "Opened your chart"
        assert staff_rows[0]["outcome"] == "allowed"
        assert staff_reference(STAFF_EMAIL) in staff_rows[0]["actor_label"]
        denied = [entry for entry in entries if entry["outcome"] == "denied"]
        assert denied and denied[0]["actor_category"] == "other_patient"

        page = client.get("/api/v1/me/access-log?limit=1&offset=1", headers=me).json()
        assert page["limit"] == 1 and page["offset"] == 1
        assert len(page["entries"]) == 1

        # Viewing the log is itself recorded.
        again = client.get("/api/v1/me/access-log", headers=me).json()
        assert any(entry["action"] == "access_log_read" for entry in again["entries"])
        assert any(entry["actor_category"] == "you" for entry in again["entries"])


def test_access_log_excludes_other_patients(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        staff = _token(client, "staff")
        assert client.get("/api/v1/patients/PAT-000002", headers=staff).status_code == 200
        me = _token(client, "patient", patient_id="PAT-000003")
        body = client.get("/api/v1/me/access-log", headers=me).json()
        assert all(entry["action"] != "chart_read" for entry in body["entries"])


def test_me_endpoints_require_patient_sign_in(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        staff = _token(client, "staff")
        for path in ("/api/v1/me/access-log", "/api/v1/me/export", "/api/v1/me/requests"):
            response = client.get(path, headers=staff)
            assert response.status_code == 403, path
            assert response.json()["error_code"] == "RBAC_FORBIDDEN"
        anonymous = client.get("/api/v1/me/export")
        assert anonymous.status_code == 401


def test_me_endpoints_with_auth_disabled(client: TestClient) -> None:
    response = client.get("/api/v1/me/export")
    assert response.status_code == 403
    assert response.json()["error_code"] == "PATIENT_LINK_REQUIRED"


def test_export_contains_own_record_and_is_audited(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        staff = _token(client, "staff")
        consent = client.post(
            "/api/v1/patients/PAT-000001/consents",
            headers=staff,
            json={
                "purpose": "continuity_of_care",
                "method": "written",
                "notice_version": "notice-2026-10",
                "granted_by_name": "Self",
            },
        )
        assert consent.status_code == 201, consent.text
        me = _token(client, "patient", patient_id="PAT-000001")
        response = client.get("/api/v1/me/export", headers=me)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["patient_id"] == "PAT-000001"
        assert body["generated_at"]
        assert body["demographics"]["patient_id"] == "PAT-000001"
        assert body["documents"], "seeded chart has documents"
        assert all("content" in doc for doc in body["documents"])
        for key in ("labs", "medications", "clinical_notes", "lifelong_events", "conditions"):
            assert key in body
        assert body["consents"][0]["consent_id"] == consent.json()["consent_id"]

        log = client.get("/api/v1/me/access-log", headers=me).json()
        exports = [entry for entry in log["entries"] if entry["action"] == "data_export"]
        assert exports and exports[0]["actor_category"] == "you"
        assert exports[0]["action_label"] == "Downloaded a copy of your data"


def test_data_subject_request_lifecycle(monkeypatch) -> None:
    with _auth_client(monkeypatch) as client:
        me = _token(client, "patient", patient_id="PAT-000001")
        created = client.post(
            "/api/v1/me/requests",
            headers=me,
            json={"request_type": "erasure", "details": "Please delete my old visit notes."},
        )
        assert created.status_code == 201, created.text
        dsr = created.json()
        assert dsr["request_id"].startswith("DSR-")
        assert dsr["status"] == "open"

        correction = client.post(
            "/api/v1/me/requests",
            headers=me,
            json={"request_type": "correction", "details": "Birth year is wrong."},
        )
        assert correction.status_code == 201
        bad_type = client.post(
            "/api/v1/me/requests",
            headers=me,
            json={"request_type": "delete_everything", "details": "now"},
        )
        assert bad_type.status_code == 422

        mine = client.get("/api/v1/me/requests", headers=me).json()
        assert mine["total"] == 2

        # Another patient sees none of these.
        other = _token(client, "patient", patient_id="PAT-000002")
        assert client.get("/api/v1/me/requests", headers=other).json()["total"] == 0
        # Patients cannot use the privacy desk.
        assert client.get("/api/v1/privacy/requests", headers=me).status_code == 403

        staff = _token(client, "staff")
        queue = client.get("/api/v1/privacy/requests?status=open", headers=staff)
        assert queue.status_code == 200, queue.text
        codes = {item["request_id"] for item in queue.json()["requests"]}
        assert dsr["request_id"] in codes
        erasures = client.get("/api/v1/privacy/requests?request_type=erasure", headers=staff).json()
        assert {item["request_type"] for item in erasures["requests"]} == {"erasure"}

        review = client.post(
            f"/api/v1/privacy/requests/{dsr['request_id']}/resolve",
            headers=staff,
            json={"status": "in_review"},
        )
        assert review.status_code == 200, review.text
        assert review.json()["status"] == "in_review"
        assert review.json()["resolved_at"] is None

        no_outcome = client.post(
            f"/api/v1/privacy/requests/{dsr['request_id']}/resolve",
            headers=staff,
            json={"status": "resolved", "resolution_note": "Retention law applies to these notes."},
        )
        assert no_outcome.status_code == 422
        assert no_outcome.json()["error_code"] == "DSR_ERASURE_OUTCOME_REQUIRED"
        short_note = client.post(
            f"/api/v1/privacy/requests/{dsr['request_id']}/resolve",
            headers=staff,
            json={"status": "resolved", "outcome": "retained_legal_hold"},
        )
        assert short_note.status_code == 422
        assert short_note.json()["error_code"] == "DSR_RESOLUTION_NOTE_REQUIRED"

        resolved = client.post(
            f"/api/v1/privacy/requests/{dsr['request_id']}/resolve",
            headers=staff,
            json={
                "status": "resolved",
                "outcome": "retained_legal_hold",
                "resolution_note": "Clinical records retained 3 years per facility retention policy; "
                "processing for non-care purposes restricted.",
            },
        )
        assert resolved.status_code == 200, resolved.text
        out = resolved.json()
        assert out["status"] == "resolved"
        assert out["outcome"] == "retained_legal_hold"
        assert out["resolved_at"]
        assert out["handled_by"] == STAFF_EMAIL

        closed = client.post(
            f"/api/v1/privacy/requests/{dsr['request_id']}/resolve",
            headers=staff,
            json={"status": "rejected", "resolution_note": "Already handled elsewhere."},
        )
        assert closed.status_code == 409
        missing = client.post(
            "/api/v1/privacy/requests/DSR-999999/resolve",
            headers=staff,
            json={"status": "in_review"},
        )
        assert missing.status_code == 404

        # The chart is untouched — erasure is a workflow, never a hard delete.
        assert client.get("/api/v1/patients/PAT-000001", headers=staff).status_code == 200
        mine_after = client.get("/api/v1/me/requests", headers=me)
        assert any(item["status"] == "resolved" for item in mine_after.json()["requests"])
        # Patient view never exposes the handling staff member's email.
        assert STAFF_EMAIL not in mine_after.text
        assert STAFF_EMAIL not in client.get("/api/v1/me/export", headers=me).text
        log = client.get("/api/v1/me/access-log", headers=me).json()
        assert any(entry["action"] == "dsr_updated" for entry in log["entries"])


def test_privacy_queue_is_org_scoped(monkeypatch) -> None:
    from app.models import Organization, Patient
    from sqlalchemy import select

    with make_client(monkeypatch, AUTH_MODE="dev-jwt", ENFORCE_ORG_SCOPE="true") as client:
        session = client.app.state.session_factory()
        try:
            other = Organization(
                org_code="ORG-000098", name="Other Facility", facility_type="clinic", active=True
            )
            session.add(other)
            session.flush()
            patient = session.scalar(select(Patient).where(Patient.patient_code == "PAT-000002"))
            assert patient is not None
            patient.org_id = other.id
            session.commit()
        finally:
            session.close()

        mine = _token(client, "patient", patient_id="PAT-000001")
        theirs = _token(client, "patient", patient_id="PAT-000002")
        own = client.post(
            "/api/v1/me/requests",
            headers=mine,
            json={"request_type": "grievance", "details": "Long wait for my records."},
        ).json()
        foreign = client.post(
            "/api/v1/me/requests",
            headers=theirs,
            json={"request_type": "nominee", "details": "Nominate my spouse."},
        ).json()

        staff = _token(client, "staff", org_code="ORG-000001")
        queue = client.get("/api/v1/privacy/requests", headers=staff)
        assert queue.status_code == 200, queue.text
        codes = {item["request_id"] for item in queue.json()["requests"]}
        assert own["request_id"] in codes
        assert foreign["request_id"] not in codes
        blocked = client.post(
            f"/api/v1/privacy/requests/{foreign['request_id']}/resolve",
            headers=staff,
            json={"status": "in_review"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["error_code"] == "ORG_SCOPE_FORBIDDEN"


def test_actor_classification_helpers() -> None:
    assert classify_actor("PAT-000001", "PAT-000001", "")[0] == "you"
    assert classify_actor("oidc-sub-123", "PAT-000001", "self")[0] == "you"
    assert classify_actor("PAT-000009", "PAT-000001", "linked=PAT-000009")[0] == "other_patient"
    assert classify_actor("OpdIngest", "PAT-000001", "")[0] == "system"
    category, label = classify_actor("a@b.example", "PAT-000001", "care_team_break_glass")
    assert category == "care_team_emergency"
    assert "a@b.example" not in label
    assert classify_actor("", "PAT-000001", "")[0] == "unknown"
    assert action_label("mcp_tool_get_patient_record").startswith("An AI assistant")
    assert action_label("some_new_action") == "Some new action"
    assert action_label("chart_read") == "Opened your chart"
