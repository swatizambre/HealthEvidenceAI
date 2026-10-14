"""India TPA desk (docs/TPA_DESK_CONTRACT.md): worklist, workspace, stages, forms, checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import AuthorizationCase, CaseQuery
from app.services.tpa_desk import (
    STAGES,
    TRANSITIONS,
    compute_clock,
    format_inr,
    mask_policy,
    urgency_key,
)
from fastapi.testclient import TestClient
from tests.conftest import make_client

API = "/api/v1/desk"
SEEDED_STAGES = {
    "PA-000005": "approved",
    "PA-000006": "draft",
    "PA-000007": "ready_to_send",
    "PA-000008": "sent",
    "PA-000009": "sent",
    "PA-000010": "query",
    "PA-000011": "query",
    "PA-000012": "approved",
    "PA-000013": "enhancement",
    "PA-000014": "discharge_pending",
    "PA-000015": "discharge_sent",
    "PA-000016": "closed",
}


# --------------------------------------------------------------------------- pure


def test_format_inr_uses_indian_grouping() -> None:
    assert format_inr(125000) == "1,25,000"
    assert format_inr(2850000) == "28,50,000"
    assert format_inr(999) == "999"
    assert format_inr(None) == ""
    assert mask_policy("NIA-31020034-2026") == "2026"


def test_every_stage_is_reachable_and_transitions_are_known() -> None:
    reachable = {"draft"}
    targets = {
        "mark_sent": "sent",
        "record_query": "query",
        "record_approval": "approved",
        "request_enhancement": "enhancement",
        "start_discharge": "discharge_pending",
        "mark_discharge_sent": "discharge_sent",
        "close": "closed",
    }
    reachable.update(targets.values())
    reachable.add("ready_to_send")  # via senior acknowledgment (review resume)
    assert reachable == set(STAGES)
    for sources in TRANSITIONS.values():
        assert sources <= set(STAGES)
    assert "closed" not in {stage for sources in TRANSITIONS.values() for stage in sources}


def _case(**fields: object) -> AuthorizationCase:
    case = AuthorizationCase(case_code="PA-999990", procedure="x", payer_type="insurer")
    for key, value in fields.items():
        setattr(case, key, value)
    return case


def test_clocks_follow_irdai_timelines() -> None:
    now = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    sent = _case(stage="sent", decision_due_at=now + timedelta(minutes=35))
    clock = compute_clock(sent, [], now=now)
    assert clock["kind"] == "insurer_decision"
    assert clock["minutes_left"] == 35 and clock["overdue"] is False

    late = _case(stage="discharge_sent", final_due_at=now - timedelta(minutes=5))
    clock = compute_clock(late, [], now=now)
    assert clock["kind"] == "final_approval" and clock["overdue"] is True

    query = CaseQuery(query_code="Q-000001", response_due_at=now + timedelta(hours=4))
    clock = compute_clock(_case(stage="query"), [query], now=now)
    assert clock["kind"] == "query_response" and clock["minutes_left"] == 240

    draft = _case(stage="draft", prep_started_at=now - timedelta(minutes=30))
    clock = compute_clock(draft, [], now=now)
    assert clock["kind"] == "prep" and clock["minutes_left"] > 0

    assert compute_clock(_case(stage="approved"), [], now=now)["kind"] == "none"


def test_urgency_sorts_overdue_then_least_time_then_oldest() -> None:
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    rows = [
        ({"overdue": False, "minutes_left": 50}, new),
        ({"overdue": True, "minutes_left": -5}, new),
        ({"overdue": False, "minutes_left": None}, old),
        ({"overdue": False, "minutes_left": 10}, new),
        ({"overdue": True, "minutes_left": -90}, new),
    ]
    ordered = sorted(rows, key=lambda row: urgency_key(row[0], row[1]))
    assert [row[0]["minutes_left"] for row in ordered] == [-90, -5, 10, 50, None]


# --------------------------------------------------------------------------- seeded API


def test_worklist_counts_and_urgency(client: TestClient) -> None:
    response = client.get(f"{API}/worklist")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 12
    stages = {item["case_id"]: item["stage"] for item in body["items"]}
    assert stages == SEEDED_STAGES
    counts = body["counts"]
    for stage in ("sent", "query", "approved"):
        assert counts[stage] == 2
    for stage in ("draft", "ready_to_send", "enhancement", "discharge_pending",
                  "discharge_sent", "closed"):
        assert counts[stage] == 1
    assert counts["overdue"] >= 2
    first = body["items"][0]
    assert first["clock"]["overdue"] is True
    flags = [item["clock"]["overdue"] for item in body["items"]]
    assert flags == sorted(flags, reverse=True)  # every overdue item comes first
    for item in body["items"]:
        assert len(item["policy_last4"]) == 4
        assert 0 <= item["readiness_percent"] <= 100
        assert item["patient_name"].endswith("(synthetic)")
    assert "medicare" not in response.text.lower()

    queries = client.get(f"{API}/worklist", params={"stage": "query"}).json()
    assert {item["case_id"] for item in queries["items"]} == {"PA-000010", "PA-000011"}
    assert all(item["clock"]["kind"] == "query_response" for item in queries["items"])
    found = client.get(f"{API}/worklist", params={"q": "medi assist"}).json()
    assert {item["case_id"] for item in found["items"]} == {"PA-000006", "PA-000010"}
    bad = client.get(f"{API}/worklist", params={"stage": "nonsense"})
    assert bad.status_code == 422


def test_stats(client: TestClient) -> None:
    body = client.get(f"{API}/stats").json()
    assert body["queries_open"] == 2
    assert body["ready_to_send"] == 1
    assert body["awaiting_senior"] == 1
    assert body["overdue"] >= 2
    assert body["due_within_60m"] >= 3
    assert isinstance(body["median_prep_minutes"], int)


def test_workspace_one_readiness_and_inline_citations(client: TestClient) -> None:
    worklist = {item["case_id"]: item for item in client.get(f"{API}/worklist").json()["items"]}
    response = client.get(f"{API}/cases/PA-000006")
    assert response.status_code == 200, response.text
    body = response.json()
    readiness = body["readiness"]
    assert readiness["percent"] == worklist["PA-000006"]["readiness_percent"]
    assert readiness["required"] - readiness["supported"] == worklist["PA-000006"]["open_items"]
    assert readiness["missing"] == 2
    assert readiness["label"] == "2 items missing"
    groups = {item["group"] for item in body["checklist"]}
    assert groups == {"form", "clinical", "documents"}
    cited = [item for item in body["checklist"] if item["citations"]]
    assert cited
    for item in cited:
        for citation in item["citations"]:
            assert citation["document_id"].startswith("DOC-")
            assert citation["chunk_id"]
            assert len(citation["excerpt"]) <= 280
    assert body["review"]["state"] == "awaiting_senior"
    assert body["case"]["stage"] == "draft"
    assert body["case"]["policy_number"] == "NIA-31020034-2026"
    assert body["patient"]["patient_id"].startswith("PAT-")
    assert body["timeline"]
    assert "approve" in body["disclaimer"].lower()  # "does not approve, deny…"

    query_case = client.get(f"{API}/cases/PA-000010").json()
    assert query_case["queries"][0]["query_id"].startswith("Q-")
    assert query_case["queries"][0]["responded_at"] is None
    assert query_case["review"]["state"] == "acknowledged"
    assert query_case["review"]["by_label"]


def test_packet_prepare_and_workspace_share_one_readiness(client: TestClient) -> None:
    workspace = client.get(f"{API}/cases/PA-000006").json()
    prepared = client.post(
        "/api/v1/authorization/prepare",
        json={
            "patient_id": workspace["patient"]["patient_id"],
            "policy_id": workspace["case"]["policy_id"],
            "case_id": "PA-000006",
        },
    )
    assert prepared.status_code == 200, prepared.text
    after = client.get(f"{API}/cases/PA-000006").json()
    assert prepared.json()["readiness_percent"] == after["readiness"]["percent"]
    listed = {
        item["case_id"]: item for item in client.get(f"{API}/worklist").json()["items"]
    }
    assert listed["PA-000006"]["readiness_percent"] == after["readiness"]["percent"]


def test_senior_resume_of_seeded_run_moves_draft_to_ready(client: TestClient) -> None:
    workspace = client.get(f"{API}/cases/PA-000006").json()
    run_id = workspace["review"]["run_id"]
    assert run_id
    blocked = client.post(f"{API}/cases/PA-000006/stage", json={"action": "mark_sent"})
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "STAGE_TRANSITION_INVALID"
    resumed = client.post(
        f"/api/v1/authorization/review/{run_id}/resume",
        json={"decision": "acknowledged", "notes": "Checked citations"},
    )
    assert resumed.status_code == 200, resumed.text
    after = client.get(f"{API}/cases/PA-000006").json()
    assert after["review"]["state"] == "acknowledged"
    assert after["case"]["stage"] == "ready_to_send"
    sent = client.post(f"{API}/cases/PA-000006/stage", json={"action": "mark_sent"})
    assert sent.status_code == 200, sent.text
    assert sent.json()["case"]["stage"] == "sent"


def _stage(client: TestClient, case_id: str, **payload: object) -> dict:
    response = client.post(f"{API}/cases/{case_id}/stage", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_full_cashless_lifecycle_for_a_new_case(client: TestClient) -> None:
    created = client.post(
        f"{API}/cases",
        json={
            "patient_id": "PAT-000003",
            "payer_type": "tpa",
            "insurer_name": "Niva Bupa (synthetic)",
            "tpa_name": "Medi Assist (synthetic)",
            "policy_number": "NB-0000-1234",
            "admission_type": "emergency",
            "admitted_at": "2026-10-14T03:30:00Z",
            "proposed_treatment": "Laparoscopic appendectomy",
            "provisional_diagnosis": "Acute appendicitis",
            "icd10_code": "k35.8",
            "estimated_cost_inr": 85000,
            "treating_doctor": "Dr. Test Surgeon",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    case_id = body["case"]["case_id"]
    assert body["case"]["stage"] == "draft"
    assert body["case"]["icd10_code"] == "K35.8"
    assert body["case"]["policy_id"] == "POL-000004"  # matched appendectomy checklist
    assert body["review"]["state"] == "not_started"

    patched = client.patch(
        f"{API}/cases/{case_id}",
        json={"form_extra": {"room_type": "Semi-private"}, "cost_breakdown_inr": {"ot": 20000}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["case"]["form_extra"]["room_type"] == "Semi-private"
    stage_edit = client.patch(f"{API}/cases/{case_id}", json={"stage": "approved"})
    assert stage_edit.status_code == 422  # stage is not an editable field

    refused = client.post(f"{API}/cases/{case_id}/stage", json={"action": "mark_sent"})
    assert refused.status_code == 409

    prepared = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000003", "policy_id": "POL-000004", "case_id": case_id},
    )
    assert prepared.status_code == 200, prepared.text
    resumed = client.post(
        f"/api/v1/authorization/review/{prepared.json()['run_id']}/resume",
        json={"decision": "acknowledged", "notes": "ok"},
    )
    assert resumed.status_code == 200, resumed.text
    assert client.get(f"{API}/cases/{case_id}").json()["case"]["stage"] == "ready_to_send"

    sent = _stage(client, case_id, action="mark_sent")
    case = sent["case"]
    assert case["stage"] == "sent"
    due = datetime.fromisoformat(case["decision_due_at"])
    assert due - datetime.fromisoformat(case["sent_at"]) == timedelta(hours=1)
    assert case["clock"]["kind"] == "insurer_decision"

    queried = _stage(client, case_id, action="record_query", text="Share USG report")
    assert queried["case"]["stage"] == "query"
    query_id = queried["queries"][0]["query_id"]
    assert 1430 <= queried["case"]["clock"]["minutes_left"] <= 1440

    early = client.post(f"{API}/cases/{case_id}/stage",
                        json={"action": "record_approval", "approved_amount_inr": 80000})
    assert early.status_code == 409
    assert early.json()["error_code"] == "STAGE_TRANSITION_INVALID"

    answered = _stage(client, case_id, action="answer_query", query_id=query_id,
                      response="USG report uploaded")
    assert answered["case"]["stage"] == "sent"
    assert answered["queries"][0]["responded_at"]

    approved = _stage(client, case_id, action="record_approval", approved_amount_inr=80000)
    assert approved["case"]["stage"] == "approved"
    assert approved["case"]["clock"]["kind"] == "none"

    enhanced = _stage(client, case_id, action="request_enhancement",
                      revised_estimate_inr=95000, reason="Extended stay")
    assert enhanced["case"]["stage"] == "enhancement"
    assert enhanced["case"]["enhancement_count"] == 1
    approved = _stage(client, case_id, action="record_approval", approved_amount_inr=95000)
    assert approved["case"]["approved_amount_inr"] == 95000

    _stage(client, case_id, action="start_discharge")
    blocked = client.post(f"{API}/cases/{case_id}/stage", json={"action": "mark_discharge_sent"})
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "DISCHARGE_CHECK_BLOCKED"
    discharged = _stage(client, case_id, action="mark_discharge_sent",
                        override_reason="Summary sent on paper")
    case = discharged["case"]
    assert case["stage"] == "discharge_sent"
    final_due = datetime.fromisoformat(case["final_due_at"])
    assert final_due - datetime.fromisoformat(case["discharge_requested_at"]) == timedelta(hours=3)

    closed = _stage(client, case_id, action="close")
    assert closed["case"]["stage"] == "closed"
    again = client.post(f"{API}/cases/{case_id}/stage", json={"action": "close"})
    assert again.status_code == 409

    audit = client.get(f"/api/v1/authorization/cases/{case_id}/audit").json()
    actions = {event["action"] for event in audit["events"]}
    assert {"desk_case_create", "desk_stage_mark_sent", "desk_stage_close"} <= actions


def test_stage_action_validation(client: TestClient) -> None:
    missing_text = client.post(f"{API}/cases/PA-000008/stage", json={"action": "record_query"})
    assert missing_text.status_code == 422
    unknown = client.post(f"{API}/cases/PA-000008/stage", json={"action": "approve"})
    assert unknown.status_code == 422
    not_found = client.get(f"{API}/cases/PA-999999")
    assert not_found.status_code == 404


def test_discharge_check_flags_seeded_diagnosis_mismatch(client: TestClient) -> None:
    response = client.get(f"{API}/cases/PA-000014/discharge-check")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blockers"
    by_code = {item["code"]: item for item in body["findings"]}
    mismatch = by_code["DIAGNOSIS_MISMATCH"]
    assert mismatch["severity"] == "blocker"
    assert "K35.8" in (mismatch["expected"] or "")
    assert "K35.3" in (mismatch["found"] or "")
    assert mismatch["citations"]
    assert by_code["BILL_EXCEEDS_APPROVED"]["severity"] == "warning"
    assert "1,12,500" in by_code["BILL_EXCEEDS_APPROVED"]["found"]
    assert by_code["PROCEDURE_MATCH"]["severity"] == "info"

    clean = client.get(f"{API}/cases/PA-000015/discharge-check").json()
    assert clean["status"] == "ok", clean
    codes = {item["code"] for item in clean["findings"]}
    assert {"DIAGNOSIS_MATCH", "BILL_WITHIN_APPROVED", "IMPLANT_INVOICE_PRESENT"} <= codes

    blocked = client.post(f"{API}/cases/PA-000014/stage", json={"action": "mark_discharge_sent"})
    assert blocked.status_code == 409


def test_preauth_form_prefills_from_case_and_chart(client: TestClient) -> None:
    response = client.get(f"{API}/cases/PA-000009/preauth-form")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "illustrative" in body["form_version"].lower()
    titles = [section["title"] for section in body["sections"]]
    assert titles == [
        "Patient & policy",
        "Treating doctor & diagnosis",
        "Admission",
        "Past history",
        "Cost estimate",
    ]
    fields = {f["key"]: f for section in body["sections"] for f in section["fields"]}
    assert fields["patient_name"]["source"] == "chart"
    assert fields["insurer_name"]["source"] == "case"
    assert fields["icd10_code"]["value"] == "I21.0"
    assert fields["surgery_name"]["required"] is True
    assert fields["history_diabetes"]["value"].startswith("Yes")
    assert "8 years" in fields["history_diabetes"]["value"]
    assert fields["cost_total"]["value"] == "₹2,45,000"
    assert isinstance(body["missing_required"], list)
    attachments = {item["label"]: item for item in body["attachments"]}
    cag = attachments["Coronary angiography (CAG) report"]
    assert cag["status"] == "SUPPORTED" and cag["citations"]

    injury = client.get(f"{API}/cases/PA-000011/preauth-form").json()
    injury_fields = {f["key"]: f for s in injury["sections"] for f in s["fields"]}
    assert injury_fields["mlc_number"]["value"] == "MLC/2026/1187"
    maternity = client.get(f"{API}/cases/PA-000010/preauth-form").json()
    maternity_fields = {f["key"]: f for s in maternity["sections"] for f in s["fields"]}
    assert maternity_fields["gpla"]["value"] == "G2 P1 L1 A0"
    lscs_attachments = {item["label"]: item for item in maternity["attachments"]}
    assert lscs_attachments["Antenatal ultrasound (growth scan) report"]["status"] == "MISSING"


def test_india_checklists_replace_us_payer_labels(client: TestClient) -> None:
    policies = client.get("/api/v1/policies", params={"limit": 50})
    assert policies.status_code == 200
    text = policies.text.lower()
    assert "medicare" not in text and "medicaid" not in text
    detail = client.get("/api/v1/policies/POL-000003").json()
    assert detail["payer_name"] == "Illustrative — confirm with each insurer/TPA"
    assert "knee" in detail["title"].lower()


# --------------------------------------------------------------------------- RBAC


def _token(client: TestClient, subject: str, *roles: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/dev-token", json={"subject": subject, "roles": list(roles)})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_desk_rbac(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        staff = _token(client, "desk-staff", "staff")
        patient = _token(client, "desk-patient", "patient")
        assert client.get(f"{API}/worklist").status_code == 401
        assert client.get(f"{API}/worklist", headers=patient).status_code == 403
        assert client.get(f"{API}/worklist", headers=staff).status_code == 200
        forbidden = client.post(
            f"{API}/cases/PA-000007/stage", headers=patient, json={"action": "mark_sent"}
        )
        assert forbidden.status_code == 403
        sent = client.post(
            f"{API}/cases/PA-000007/stage", headers=staff, json={"action": "mark_sent"}
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["case"]["stage"] == "sent"


# --------------------------------------------------------------------------- migration


def test_tpa_desk_migration_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from app.db.base import Base
    from sqlalchemy import create_engine, inspect

    db_url = f"sqlite:///{tmp_path / 'desk.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    engine = create_engine(db_url)
    from app import models  # noqa: F401

    skipped = {"case_queries", "consent_records", "data_subject_requests", "hospital_pipeline_runs"}
    base_tables = [table for name, table in Base.metadata.tables.items() if name not in skipped]
    Base.metadata.create_all(bind=engine, tables=base_tables)
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    try:
        command.upgrade(cfg, "head")
        inspector = inspect(engine)
        assert "case_queries" in inspector.get_table_names()
        columns = {col["name"] for col in inspector.get_columns("authorization_cases")}
        assert {"stage", "payer_type", "decision_due_at", "final_due_at"} <= columns
        command.downgrade(cfg, "20261013_0003")
        assert "case_queries" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")  # idempotent re-upgrade (guards existing columns)
        assert "case_queries" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        get_settings.cache_clear()
