"""Supervisor-routed LangGraph orchestration (evidence prep only)."""

from __future__ import annotations

from app.agents.supervisor import open_criterion_ids, plan_orchestration, should_rereetrieve
from fastapi.testclient import TestClient


def test_supervisor_plans_imaging_when_mri_procedure() -> None:
    plan = plan_orchestration(
        procedure="Knee MRI documentation pack",
        criteria=[{"description": "Conservative therapy documented", "criterion_id": "C1"}],
        a2a_enabled=True,
    )
    assert plan["need_imaging"] is True
    assert plan["retrieval_strategy"] == "expanded_hybrid"
    assert plan["max_retrieve_passes"] == 2


def test_supervisor_skips_imaging_without_keywords() -> None:
    plan = plan_orchestration(
        procedure="Office visit documentation",
        criteria=[{"description": "Blood pressure logged", "criterion_id": "C1"}],
        a2a_enabled=True,
    )
    assert plan["need_imaging"] is False


def test_supervisor_imaging_off_when_a2a_disabled() -> None:
    plan = plan_orchestration(
        procedure="CT abdomen",
        criteria=[],
        a2a_enabled=False,
    )
    assert plan["need_imaging"] is False


def test_should_rereetrieve_once_for_open_items() -> None:
    state = {
        "retrieve_pass": 0,
        "max_retrieve_passes": 2,
        "criterion_results": [
            {"criterion_id": "C1", "status": "MISSING"},
            {"criterion_id": "C2", "status": "SUPPORTED"},
        ],
        "critic_notes": [],
    }
    assert should_rereetrieve(state) is True
    state["retrieve_pass"] = 1
    assert should_rereetrieve(state) is False
    assert open_criterion_ids(state) == ["C1"]


def test_parallel_retrieve_still_returns_evidence(client: TestClient) -> None:
    response = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000001", "policy_id": "POL-000001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("run_id")
    nodes = [step.get("node") for step in body.get("agent_trace") or []]
    assert "supervisor_plan" in nodes
    assert "retrieve_evidence" in nodes


def test_review_trace_includes_supervisor(client: TestClient) -> None:
    from tests.helpers import review

    body = review(
        client,
        "PAT-000001",
        case_id="PA-000001",
        procedure="MRI lumbar documentation",
    )
    nodes = [step.get("node") for step in body.get("agent_trace") or []]
    assert "supervisor_plan" in nodes
    assert "retrieve_evidence" in nodes
    # MRI + A2A test env → imaging branch executed (consult or explicit skip label).
    assert any("a2a" in str(n) or "imaging" in str(n) for n in nodes)
