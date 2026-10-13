"""LLM provider wiring for Gemini, local, and failover."""

import httpx
import pytest
from app.agents.providers import LIVE_PROVIDERS, build_llm, complete_report_with_failover
from app.core.config import Settings
from app.core.exceptions import LLMUnavailable


def test_gemini_is_a_live_provider() -> None:
    assert "gemini" in LIVE_PROVIDERS
    assert "local" in LIVE_PROVIDERS


def test_gemini_requires_api_key() -> None:
    settings = Settings(llm_provider="gemini", gemini_api_key="", model_name="gemini-3.1-flash-lite")
    with pytest.raises(LLMUnavailable, match="GEMINI_API_KEY"):
        build_llm(settings)


def test_gemini_complete_report_uses_generate_content(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="test-key",
        gemini_model_name="gemini-3.1-flash-lite",
        model_name="",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
    )

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Grounded summary from contexts only."}]}}
                ]
            }

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        assert url.endswith("/models/gemini-3.1-flash-lite:generateContent")
        assert kwargs["params"] == {"key": "test-key"}
        body = kwargs["json"]
        assert isinstance(body, dict)
        assert "contents" in body
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_llm(settings)
    assert provider.name == "gemini"
    assert provider.chat_api == "google_genai"
    text = provider.complete_report("Summarize", ["SUPPORTED=5"])
    assert "Grounded summary" in text


def test_ollama_uses_chat_api_not_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        llm_provider="ollama",
        ollama_model_name="medgemma:4b",
        model_name="",
        ollama_base_url="http://127.0.0.1:11434",
        gemini_api_key="should-not-be-used",
        gemini_model_name="gemini-3.1-flash-lite",
    )
    seen: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"message": {"role": "assistant", "content": "Ollama chat summary."}}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        assert "/api/chat" in url
        assert "generateContent" not in url
        assert "generativelanguage.googleapis.com" not in url
        body = kwargs["json"]
        assert isinstance(body, dict)
        assert body["model"] == "medgemma:4b"
        assert body["messages"][0]["role"] == "system"
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_llm(settings)
    assert provider.name == "ollama"
    assert provider.chat_api == "ollama_chat"
    text = provider.complete_report("Summarize", ["SUPPORTED=5"])
    assert "Ollama chat summary" in text
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"


def test_model_for_provider_keeps_names_separate() -> None:
    settings = Settings(
        llm_provider="ollama",
        gemini_model_name="gemini-3.1-flash-lite",
        ollama_model_name="medgemma:4b",
        model_name="",
    )
    assert settings.model_for_provider("gemini") == "gemini-3.1-flash-lite"
    assert settings.model_for_provider("ollama") == "medgemma:4b"
    # Switching provider must not reuse the other stack's model id.
    gemini_settings = Settings(
        llm_provider="gemini",
        gemini_api_key="x",
        gemini_model_name="gemini-3.1-flash-lite",
        ollama_model_name="medgemma:4b",
        model_name="medgemma:4b",  # leftover — ignored for gemini
    )
    assert gemini_settings.model_for_provider("gemini") == "gemini-3.1-flash-lite"



def test_local_provider_always_phrases() -> None:
    settings = Settings(llm_provider="local", model_name="local-grounded")
    provider = build_llm(settings)
    assert provider.name == "local"
    text = provider.complete_report(
        "Summarize",
        [
            "SUPPORTED: Medication review due (situation) is documented.",
            "SUPPORTED: Gingivitis (disorder) is documented.",
        ],
    )
    assert "Chart check summary" in text
    assert "BEGIN_UNTRUSTED" not in text
    assert "2/2" in text
    assert "not a clinical decision" in text.lower()


def test_failover_ends_on_local_when_others_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="bad",
        llm_fallback_providers="ollama",
        model_name="gemini-1.5-flash",
    )

    def fake_build(settings_obj: Settings, provider: str | None = None) -> object:
        name = (provider or settings_obj.llm_provider).strip().lower()
        raise LLMUnavailable(f"{name} down")

    monkeypatch.setattr("app.agents.providers.build_llm", fake_build)
    text, used = complete_report_with_failover(settings, "Summarize", ["SUPPORTED=5"])
    assert used == "local"
    assert "Chart check summary" in text


def test_report_failover_uses_next_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="bad-key",
        llm_fallback_providers="ollama",
        model_name="gemini-1.5-flash",
        ollama_base_url="http://127.0.0.1:11434",
    )
    calls: list[str] = []

    class FakeGemini:
        name = "gemini"

        def complete_report(self, prompt: str, contexts: list[str]) -> str:
            del prompt, contexts
            calls.append("gemini")
            raise LLMUnavailable("gemini down")

    class FakeOllama:
        name = "ollama"

        def complete_report(self, prompt: str, contexts: list[str]) -> str:
            del prompt, contexts
            calls.append("ollama")
            return "Ollama grounded summary."

    def fake_build(settings_obj: Settings, provider: str | None = None) -> object:
        name = (provider or settings_obj.llm_provider).strip().lower()
        if name == "gemini":
            return FakeGemini()
        if name == "ollama":
            return FakeOllama()
        raise LLMUnavailable(name)

    monkeypatch.setattr("app.agents.providers.build_llm", fake_build)
    text, used = complete_report_with_failover(settings, "Summarize", ["SUPPORTED=5"])
    assert used == "ollama"
    assert "Ollama grounded summary" in text
    assert calls == ["gemini", "ollama"]
