"""Ollama chat provider — distinct from Google GenAI.

Uses Ollama's native /api/chat endpoint (not Gemini generateContent).
Model comes from OLLAMA_MODEL_NAME (or legacy MODEL_NAME when it looks like an Ollama tag).
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.exceptions import LLMUnavailable

_SYSTEM = (
    "You are an evidence-organization assistant for synthetic healthcare records. "
    "Answer only from provided contexts. Do not diagnose, prescribe, approve, or deny care."
)


class OllamaProvider:
    name = "ollama"
    chat_api = "ollama_chat"  # /api/chat

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.model_for_provider("ollama")

    def complete(self, query: str, contexts: list[str]) -> str:
        return self._chat_ollama(
            
                f"Query: {query}\n\nContexts:\n{self._join(contexts)}"
            
        )

    def complete_report(self, prompt: str, contexts: list[str]) -> str:
        return self._chat_ollama(
            
                "Phrase a grounded evidence review summary from the provided contexts only. "
                "Do not invent citations or clinical decisions.\n\n"
                f"{prompt}\n\nContexts:\n{self._join(contexts)}"
            
        )

    def score_criteria(
        self,
        *,
        criteria: list,
        notes: list,
        labs: list,
        retrieved_hits: list[dict],
    ) -> list:
        from app.services.clinical_intelligence import (
            _build_contexts,
            _clinical_prompt,
            _evaluations_from_payload,
            _evidence_catalog,
            _parse_json,
        )

        contexts = _build_contexts(notes, labs, retrieved_hits)
        catalog = _evidence_catalog(notes, labs, retrieved_hits)
        prompt = _clinical_prompt(criteria, catalog)
        raw = self._chat_ollama(
            
                "Return JSON only. No markdown fences. "
                "Clinical evidence intelligence for synthetic prior-auth prep.\n\n"
                f"{prompt}\n\nContexts:\n{self._join(contexts)}"
            
        )
        payload = _parse_json(raw)
        return _evaluations_from_payload(payload, criteria, catalog)

    def _chat_ollama(self, user_prompt: str) -> str:
        """Ollama-native chat call — never hits Google GenAI."""
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        try:
            response = httpx.post(
                url,
                json={
                    "model": self._model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    "options": {"temperature": 0},
                },
                timeout=self._settings.llm_timeout_seconds,
            )
            if response.status_code >= 400:
                detail = response.text.replace("\n", " ").strip()[:240]
                raise LLMUnavailable(
                    f"Ollama chat failed ({response.status_code}) for model {self._model}: {detail}"
                )
            payload = response.json()
            message = payload.get("message") if isinstance(payload, dict) else None
            text = ""
            if isinstance(message, dict):
                text = str(message.get("content") or "").strip()
            if not text:
                # Older Ollama builds may still echo generate-style fields.
                text = str(payload.get("response") or "").strip()
            if not text:
                raise LLMUnavailable(f"Ollama returned an empty chat completion for {self._model}.")
            return text
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(f"Ollama chat provider failed: {exc}") from exc

    @staticmethod
    def _join(contexts: list[str]) -> str:
        if not contexts:
            return "(none)"
        return "\n---\n".join(contexts[:8])
