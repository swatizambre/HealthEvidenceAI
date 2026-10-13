"""Build the configured LLM provider."""

from __future__ import annotations

from app.agents.providers.anthropic import AnthropicProvider
from app.agents.providers.base import LLMProvider
from app.agents.providers.gemini import GeminiProvider
from app.agents.providers.local import LocalGroundedProvider
from app.agents.providers.ollama import OllamaProvider
from app.agents.providers.openai import OpenAIProvider
from app.core.config import Settings
from app.core.exceptions import LLMUnavailable

LIVE_PROVIDERS = frozenset({"openai", "anthropic", "ollama", "gemini", "local"})


_CLOUD_PHI_PROVIDERS = frozenset({"openai", "anthropic", "gemini"})


def build_llm(settings: Settings, provider: str | None = None) -> LLMProvider:
    name = (provider or settings.llm_provider).strip().lower()
    if name in _CLOUD_PHI_PROVIDERS and settings.external_llm_phi_blocked():
        raise LLMUnavailable(
            f"Provider {name!r} blocked while ALLOW_PHI is on without "
            "LLM_BAA_ATTESTED and LLM_PHI_EGRESS_ALLOWED."
        )
    if name == "openai":
        return OpenAIProvider(settings)
    if name == "anthropic":
        return AnthropicProvider(settings)
    if name == "ollama":
        return OllamaProvider(settings)
    if name == "gemini":
        return GeminiProvider(settings)
    if name == "local":
        return LocalGroundedProvider(settings)
    raise LLMUnavailable(
        f"Unsupported LLM_PROVIDER={provider or settings.llm_provider!r}. "
        f"Supported providers: {', '.join(sorted(LIVE_PROVIDERS))}."
    )


def complete_report_with_failover(
    settings: Settings, prompt: str, contexts: list[str]
) -> tuple[str, str]:
    """Try primary then fallback providers. Returns (text, provider_name)."""
    errors: list[str] = []
    for name in settings.llm_provider_chain():
        if name in _CLOUD_PHI_PROVIDERS and settings.external_llm_phi_blocked():
            errors.append(f"{name}: blocked (PHI egress / BAA not attested)")
            continue
        try:
            provider = build_llm(settings, name)
            return provider.complete_report(prompt, contexts), name
        except LLMUnavailable as exc:
            errors.append(f"{name}: {exc.message}")
            continue
    # Last-resort local phrasing so the review graph always completes.
    local = LocalGroundedProvider(settings)
    return local.complete_report(prompt, contexts), "local"
