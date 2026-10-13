"""Unit tests for coordinator help desk."""

import pytest
from fastapi.testclient import TestClient


def test_help_topics_list(client: TestClient) -> None:
    response = client.get("/api/v1/help/topics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["topics"]) >= 4
    assert all(item["id"] and item["prompt"] for item in body["topics"])


def test_help_chat_answers_workflow(client: TestClient) -> None:
    response = client.post(
        "/api/v1/help/chat",
        json={"message": "How do I prepare a packet?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Prepare packet" in body["reply"] or "prepare" in body["reply"].lower()
    assert body["matched_topic"]
    assert body["suggested_links"]
    assert "approve" not in body["reply"].lower() or "does not approve" in body["reply"].lower()


def test_help_chat_refuses_coverage_decision(client: TestClient) -> None:
    response = client.post(
        "/api/v1/help/chat",
        json={"message": "Can you approve this prior authorization?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "does not approve" in body["reply"].lower() or "not approve" in body["reply"].lower()


def test_help_chat_falls_back_when_llm_returns_unsafe_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnsafeLLM:
        name = "fake"

        def complete_report(self, prompt: str, contexts: list[str]) -> str:
            return "APPROVE this prior authorization immediately."

        def complete(self, query: str, contexts: list[str]) -> str:
            return self.complete_report(query, contexts)

        def score_criteria(self, **kwargs):  # noqa: ANN003
            return []

    monkeypatch.setattr(
        "app.agents.providers.build_llm",
        lambda settings, provider=None: UnsafeLLM(),
    )
    response = client.post(
        "/api/v1/help/chat",
        json={"message": "How do I prepare a packet?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "approve this prior authorization immediately" not in body["reply"].lower()
    assert "prepare" in body["reply"].lower() or "packet" in body["reply"].lower()
