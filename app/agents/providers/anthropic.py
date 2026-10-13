"""Anthropic Messages API provider."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import LLMUnavailable


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key.strip():
            raise LLMUnavailable("ANTHROPIC_API_KEY is required for LLM_PROVIDER=anthropic.")
        self._settings = settings
        self._model = settings.model_for_provider("anthropic")

    def complete(self, query: str, contexts: list[str]) -> str:
        return self._chat(
            system=(
                "You are an evidence-organization assistant for synthetic healthcare records. "
                "Answer only from the provided contexts. Do not diagnose, prescribe, approve, or deny care."
            ),
            user=f"Query: {query}\n\nContexts:\n{self._join(contexts)}",
        )

    def complete_report(self, prompt: str, contexts: list[str]) -> str:
        return self._chat(
            system="Phrase a grounded evidence review from contexts only. No invented citations.",
            user=f"{prompt}\n\nContexts:\n{self._join(contexts)}",
        )

    def score_criteria(
        self,
        *,
        criteria: list[Any],
        notes: list[Any],
        labs: list[Any],
        retrieved_hits: list[dict[str, Any]],
    ) -> list[Any]:
        del criteria, notes, labs, retrieved_hits
        return []

    def _chat(self, *, system: str, user: str) -> str:
        try:
            response = httpx.post(
                f"{self._settings.anthropic_base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": self._settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 800,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            blocks = payload.get("content") or []
            text = "".join(
                block.get("text", "") for block in blocks if isinstance(block, dict)
            ).strip()
            if not text:
                raise LLMUnavailable("Anthropic returned an empty completion.")
            return text
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(f"Anthropic provider failed: {exc}") from exc

    @staticmethod
    def _join(contexts: list[str]) -> str:
        if not contexts:
            return "(none)"
        return "\n---\n".join(contexts[:8])
