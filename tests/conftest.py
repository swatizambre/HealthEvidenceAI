"""Shared API fixtures with an isolated in-memory database."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.config import get_settings
from fastapi.testclient import TestClient
from tests.fakes.llm import TestDoubleLLM


def make_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raise_server_exceptions: bool = True,
    database_url: str | None = None,
    **env: str,
) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", database_url or "sqlite://")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("MODEL_NAME", "llama3.2")
    monkeypatch.setenv("SEED_ON_STARTUP", "true")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("IMAGING_BACKEND", "monai")
    monkeypatch.setenv("A2A_ENABLED", "true")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    def _double(settings: object = None, provider: str | None = None) -> TestDoubleLLM:
        del settings, provider
        return TestDoubleLLM()

    def _failover(settings: object, prompt: str, contexts: list[str]) -> tuple[str, str]:
        del settings
        return TestDoubleLLM().complete_report(prompt, contexts), "test-double"

    monkeypatch.setattr("app.agents.llm.build_llm", _double)
    monkeypatch.setattr("app.agents.providers.build_llm", _double)
    monkeypatch.setattr("app.agents.providers.complete_report_with_failover", _failover)
    monkeypatch.setattr("app.api.routes.evidence.build_llm", _double)
    from app.agents.checkpoints import reset_checkpointer
    from app.agents.runs import clear_runs

    reset_checkpointer()
    clear_runs()
    from app.main import create_app

    client = TestClient(create_app(), raise_server_exceptions=raise_server_exceptions)
    # Lifespan may open a durable saver; force memory for isolated unit tests.
    reset_checkpointer()
    return client


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    test_client = make_client(monkeypatch)
    with test_client:
        yield test_client
    get_settings.cache_clear()
