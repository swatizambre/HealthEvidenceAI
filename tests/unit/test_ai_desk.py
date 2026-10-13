"""AI desk insights + MCP tool catalog."""

from fastapi.testclient import TestClient


def test_desk_insights_for_care_team(client: TestClient) -> None:
    response = client.get("/api/v1/insights")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["insights"]
    assert "Care coordinator" in body["agent_fleet"]
    assert body["llm_provider"]
    assert body["disclaimer"]
    assert "LangGraph" not in body["insights"][0]["detail"]
    assert "Orchestrator:" not in body["insights"][0]["title"]


def test_mcp_tool_catalog(client: TestClient) -> None:
    response = client.get("/api/v1/tools")
    assert response.status_code == 200, response.text
    body = response.json()
    names = {item["name"] for item in body["tools"]}
    assert "search_clinical_evidence" in names
    assert "get_patient_record" in names
    assert body["agents"]


def test_prepare_exposes_agent_desk_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/authorization/prepare",
        json={"patient_id": "PAT-000002", "policy_id": "POL-000001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ai_brief"]
    assert body["agent_trace"]
    assert body["mcp_tools_used"]
    if body["gaps"]:
        assert body["gaps"][0]["draft_suggestion"]
        assert "Agent" not in body["gaps"][0]["agent"]
    assert "ai_clinical" not in (body.get("ai_brief") or "").lower()
    assert "HITL" not in (body.get("ai_brief") or "")
    for step in body.get("agent_trace") or []:
        detail = (step.get("detail") or "").lower()
        assert "hits=" not in detail
        assert "scoring=" not in detail
        assert "monai" not in detail
