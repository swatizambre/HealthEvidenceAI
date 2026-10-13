"""OpenAI chat completions provider."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import LLMUnavailable


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key.strip():
            raise LLMUnavailable("OPENAI_API_KEY is required for LLM_PROVIDER=openai.")
        self._settings = settings
        self._model = settings.model_for_provider("openai")

    def complete(self, query: str, contexts: list[str]) -> str:
        return self._chat(
            system=(
                "You are an evidence-organization assistant for synthetic healthcare records. "
                "Answer only from the provided contexts. Cite nothing that is not present. "
                "Do not diagnose, prescribe, approve, or deny care."
            ),
            user=f"Query: {query}\n\nContexts:\n{self._join(contexts)}",
        )

    def complete_report(self, prompt: str, contexts: list[str]) -> str:
        return self._chat(
            system=(
                "Phrase a grounded evidence review summary from the provided contexts only. "
                "Do not invent citations or clinical decisions."
            ),
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
                f"{self._settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0,
                },
                timeout=self._settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMUnavailable("OpenAI returned an empty completion.")
            return content.strip()
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(f"OpenAI provider failed: {exc}") from exc

    @staticmethod
    def _join(contexts: list[str]) -> str:
        if not contexts:
            return "(none)"
        return "\n---\n".join(contexts[:8])
