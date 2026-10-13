"""Ten-persona end-to-end matrix — exercise the system the way different users do.

Runs under AUTH_MODE=dev-jwt with the seeded synthetic catalog. LLM calls use the
test double from conftest (no live Ollama required).
"""

from __future__ import annotations

from app.services.synthetic import get_demo_procedure
from fastapi.testclient import TestClient
from tests.conftest import make_client

POLICY = "POL-000001"
COMPLETE = "PAT-000001"
GAPPED = "PAT-000002"
GAPPED_CASE = "PA-000002"
PROCEDURE = get_demo_procedure()


def _auth_client(monkeypatch) -> TestClient:
    return make_client(monkeypatch, AUTH_MODE="dev-jwt")


def _token(client: TestClient, *roles: str, patient_id: str | None = None, subject: str = "persona") -> str:
    body: dict = {"subject": subject, "roles": list(roles)}
    if patient_id:
        body["patient_id"] = patient_id
        body["subject"] = patient_id
    response = client.post("/api/v1/auth/dev-token", json=body)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_persona_01_pa_staff_prepare_gapped_packet(monkeypatch) -> None:
    """PA staff: list → open gapped chart → prepare → gaps + next action."""
    with _auth_client(monkeypatch) as client:
        token = _token(client, "staff", subject="pa-staff-1")
        headers = _hdr(token)

        listing = client.get("/api/v1/patients", headers=headers)
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] >= 2

        chart = client.get(f"/api/v1/patients/{GAPPED}", headers=headers)
        assert chart.status_code == 200, chart.text

        packet = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        assert packet.status_code == 200, packet.text
        body = packet.json()
        assert "readiness_percent" in body
        assert isinstance(body.get("gaps"), list)
        for gap in body["gaps"]:
            label = (gap.get("label") or "").lower()
            assert "employment" not in label
            assert "(situation)" not in label
        if body.get("gap_count", 0) > 0:
            assert body.get("next_best_action") is not None


def test_persona_02_senior_hitl_resume(monkeypatch) -> None:
    """Senior: interactive review pauses, then resume with needs_documentation."""
    with _auth_client(monkeypatch) as client:
        senior = _token(client, "senior_clinician", subject="senior-2")
        headers = _hdr(senior)

        paused = client.post(
            "/api/v1/authorization/review",
            headers=headers,
            json={
                "patient_id": GAPPED,
                "policy_id": POLICY,
                "procedure": PROCEDURE,
                "case_id": GAPPED_CASE,
                "interactive": True,
            },
        )
        assert paused.status_code == 200, paused.text
        body = paused.json()
        assert body["awaiting_human_review"] is True
        run_id = body["run_id"]

        resumed = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            headers=headers,
            json={"decision": "needs_documentation", "notes": "Persona senior review"},
        )
        assert resumed.status_code == 200, resumed.text


def test_persona_03_resident_prepare_ok_resume_forbidden(monkeypatch) -> None:
    """Resident: prepare + start review OK; HITL resume forbidden."""
    with _auth_client(monkeypatch) as client:
        resident = _token(client, "resident", subject="resident-3")
        headers = _hdr(resident)

        prep = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        assert prep.status_code == 200, prep.text

        paused = client.post(
            "/api/v1/authorization/review",
            headers=headers,
            json={
                "patient_id": GAPPED,
                "policy_id": POLICY,
                "procedure": PROCEDURE,
                "case_id": GAPPED_CASE,
                "interactive": True,
            },
        )
        assert paused.status_code == 200, paused.text
        run_id = paused.json()["run_id"]

        forbidden = client.post(
            f"/api/v1/authorization/review/{run_id}/resume",
            headers=headers,
            json={"decision": "acknowledged", "notes": "resident attempt"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error_code"] == "RBAC_FORBIDDEN"


def test_persona_04_patient_self_chart_ok(monkeypatch) -> None:
    """Patient: lifelong / essentials / timeline for linked self chart."""
    with _auth_client(monkeypatch) as client:
        token = _token(client, "patient", patient_id=COMPLETE)
        headers = _hdr(token)

        for path in (
            f"/api/v1/patients/{COMPLETE}",
            f"/api/v1/patients/{COMPLETE}/lifelong",
            f"/api/v1/patients/{COMPLETE}/essentials",
            f"/api/v1/patients/{COMPLETE}/timeline",
        ):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, f"{path} -> {response.text}"


def test_persona_05_patient_cross_chart_forbidden(monkeypatch) -> None:
    """Patient: another chart and prepare are forbidden."""
    with _auth_client(monkeypatch) as client:
        token = _token(client, "patient", patient_id=COMPLETE)
        headers = _hdr(token)

        other = client.get(f"/api/v1/patients/{GAPPED}", headers=headers)
        assert other.status_code == 403
        assert other.json()["error_code"] == "PATIENT_SCOPE_FORBIDDEN"

        lifelong = client.get(f"/api/v1/patients/{GAPPED}/lifelong", headers=headers)
        assert lifelong.status_code == 403

        prepare = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        assert prepare.status_code == 403


def test_persona_06_staff_complete_chart_ready(monkeypatch) -> None:
    """Staff: prepare complete profile — readiness at least as high as gapped."""
    with _auth_client(monkeypatch) as client:
        token = _token(client, "staff", subject="staff-complete-6")
        headers = _hdr(token)

        complete = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": COMPLETE, "policy_id": POLICY},
        )
        gapped = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        assert complete.status_code == 200, complete.text
        assert gapped.status_code == 200, gapped.text
        ready = complete.json()["readiness_percent"]
        gapped_ready = gapped.json()["readiness_percent"]
        assert ready >= gapped_ready
        assert complete.json()["gap_count"] <= gapped.json()["gap_count"]


def test_persona_07_staff_visit_note_then_reprepare(monkeypatch) -> None:
    """Staff: visit-note ingest on existing patient, then re-prepare."""
    with _auth_client(monkeypatch) as client:
        token = _token(client, "staff", subject="staff-visit-7")
        headers = _hdr(token)

        ingest = client.post(
            "/api/v1/opd/ingest",
            headers=headers,
            json={
                "patient_id": GAPPED,
                "mrn": "UHID-PERSONA-7",
                "visit_number": "OPD-PERSONA-7",
                "encounter_id": "ENC-PERSONA-7",
                "note": "Persona visit note. Documented lab follow-up for cholesterol.",
                "labs": [
                    {
                        "test_name": "Cholesterol [Mass/volume] in Serum or Plasma",
                        "value": "180",
                        "unit": "mg/dL",
                    }
                ],
                "medications": [],
                "procedure": "Plain X-ray of ankle region (procedure)",
                "policy_id": POLICY,
                "source": "opd_manual",
                "synthetic": True,
                "consent_attested": True,
            },
        )
        assert ingest.status_code in (200, 201), ingest.text
        assert ingest.json()["patient_id"] == GAPPED

        packet = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        assert packet.status_code == 200, packet.text
        assert "readiness_percent" in packet.json()


def test_persona_08_admin_care_desk(monkeypatch) -> None:
    """Admin: insights, worklist, stats, tools — no infra jargon leaks."""
    with _auth_client(monkeypatch) as client:
        token = _token(client, "admin", subject="admin-8")
        headers = _hdr(token)

        for path in (
            "/api/v1/insights",
            "/api/v1/worklist",
            "/api/v1/stats",
            "/api/v1/tools",
            "/api/v1/organizations",
        ):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, f"{path} -> {response.text}"

        insights = client.get("/api/v1/insights", headers=headers).json()
        blob = str(insights).lower()
        assert "langgraph" not in blob
        assert insights.get("insights")
        assert insights.get("agent_fleet")

        tools = client.get("/api/v1/tools", headers=headers).json()
        names = {item["name"] for item in tools.get("tools", [])}
        assert "search_clinical_evidence" in names
        assert "get_patient_record" in names


def test_persona_09_anonymous_and_bad_token(monkeypatch) -> None:
    """Anonymous / garbage Bearer → 401 on protected routes."""
    with _auth_client(monkeypatch) as client:
        protected = (
            "/api/v1/patients",
            "/api/v1/worklist",
            "/api/v1/stats",
            "/api/v1/insights",
        )
        for path in protected:
            anon = client.get(path)
            assert anon.status_code == 401, f"anon {path} -> {anon.status_code}"
            bad = client.get(path, headers={"Authorization": "Bearer not-a-real-token"})
            assert bad.status_code == 401, f"bad {path} -> {bad.status_code}"


def test_persona_10_concurrent_staff_chart_hammer(monkeypatch) -> None:
    """Chart hammer under load — no DATABASE_ERROR / 503.

    In-memory SQLite + TestClient is not multi-thread safe (StaticPool), so this
    persona uses a rapid sequential burst that still exercises the same endpoints
    a multi-tab chart open would hit.
    """
    with _auth_client(monkeypatch) as client:
        token = _token(client, "staff", subject="staff-hammer-10")
        headers = _hdr(token)
        read_paths = [
            f"/api/v1/patients/{GAPPED}",
            f"/api/v1/patients/{GAPPED}/lifelong",
            f"/api/v1/patients/{GAPPED}/essentials",
            f"/api/v1/patients/{GAPPED}/timeline",
        ]

        results: list[tuple[str, int, str]] = []
        for _ in range(5):
            for path in read_paths:
                response = client.get(path, headers=headers)
                code = response.json().get("error_code", "") if response.content else ""
                results.append((path, response.status_code, str(code)))

        prep = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        prep_code = prep.json().get("error_code", "") if prep.content else ""
        results.append(("/api/v1/authorization/prepare", prep.status_code, str(prep_code)))

        # Second prepare while chart reads continue (serial interleave).
        for path in read_paths:
            response = client.get(path, headers=headers)
            code = response.json().get("error_code", "") if response.content else ""
            results.append((path, response.status_code, str(code)))
        prep2 = client.post(
            "/api/v1/authorization/prepare",
            headers=headers,
            json={"patient_id": GAPPED, "policy_id": POLICY},
        )
        prep2_code = prep2.json().get("error_code", "") if prep2.content else ""
        results.append(("/api/v1/authorization/prepare", prep2.status_code, str(prep2_code)))

        failures = [
            (path, status, err)
            for path, status, err in results
            if status != 200 or err == "DATABASE_ERROR"
        ]
        assert not failures, f"hammer failures: {failures[:5]}"
