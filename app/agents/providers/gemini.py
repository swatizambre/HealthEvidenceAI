"""Google Gemini GenAI chat provider — distinct from Ollama.

Uses Google generateContent (contents/parts). Model from GEMINI_MODEL_NAME.
Never calls Ollama /api/chat.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.exceptions import LLMUnavailable

# Prefer cost-effective Flash-Lite first; keep fuller Flash models as failover.
_MODEL_CANDIDATES = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
)


class GeminiProvider:
    name = "gemini"
    chat_api = "google_genai"  # :generateContent

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key.strip():
            raise LLMUnavailable("GEMINI_API_KEY is required for LLM_PROVIDER=gemini.")
        self._settings = settings
        self._model = settings.model_for_provider("gemini")

    def complete(self, query: str, contexts: list[str]) -> str:
        return self._chat_genai(
            
                "You are an evidence-organization assistant for synthetic healthcare records. "
                "Answer only from the provided contexts. Cite nothing that is not present. "
                "Do not diagnose, prescribe, approve, or deny care.\n\n"
                f"Query: {query}\n\nContexts:\n{self._join(contexts)}"
            
        )

    def complete_report(self, prompt: str, contexts: list[str]) -> str:
        return self._chat_genai(
            
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
        raw = self._chat_genai(
            
                "Return JSON only. No markdown fences. "
                "Clinical evidence intelligence for synthetic prior-auth prep.\n\n"
                f"{prompt}\n\nContexts:\n{self._join(contexts)}"
            
        )
        payload = _parse_json(raw)
        return _evaluations_from_payload(payload, criteria, catalog)

    def _chat_genai(self, prompt: str) -> str:
        """Google GenAI chat call — never hits Ollama."""
        errors: list[str] = []
        for model in self._models():
            try:
                return self._generate_content(prompt, model)
            except LLMUnavailable as exc:
                message = str(exc.message)
                errors.append(message)
                if _is_fatal_provider_error(message):
                    break
                continue
        joined = " | ".join(errors[:3]) if errors else "no models attempted"
        raise LLMUnavailable(f"Gemini GenAI failed for all candidate models. {joined}")

    def _models(self) -> list[str]:
        primary = self._model.removeprefix("models/")
        if primary.startswith("local") or primary in {"", "none"} or ":" in primary:
            primary = "gemini-3.1-flash-lite"
        ordered = [primary]
        for item in _MODEL_CANDIDATES:
            if item not in ordered:
                ordered.append(item)
        return ordered

    def _generate_content(self, prompt: str, model: str) -> str:
        url = (
            f"{self._settings.gemini_base_url.rstrip('/')}/models/"
            f"{model}:generateContent"
        )
        try:
            response = httpx.post(
                url,
                params={"key": self._settings.gemini_api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0},
                },
                timeout=self._settings.llm_timeout_seconds,
            )
            if response.status_code >= 400:
                detail = _safe_error_body(response.text)
                raise LLMUnavailable(
                    f"Gemini GenAI failed ({response.status_code}) for model {model}: {detail}"
                )
            payload = response.json()
            text = _extract_text(payload)
            if not text:
                raise LLMUnavailable(f"Gemini returned an empty completion for model {model}.")
            return text
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(f"Gemini GenAI provider failed: {_redact(str(exc))}") from exc

    @staticmethod
    def _join(contexts: list[str]) -> str:
        if not contexts:
            return "(none)"
        return "\n---\n".join(contexts[:8])


def _is_fatal_provider_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "(401)",
            "(403)",
            "(429)",
            "exceeded your current quota",
            "api key",
            "permission denied",
        )
    )


def _extract_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content") or {}
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts") or []
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _safe_error_body(text: str) -> str:
    return _redact(text.replace("\n", " ").strip()[:240])


def _redact(text: str) -> str:
    import re

    cleaned = re.sub(r"(key=)[^&\s]+", r"\1***", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bAIza[0-9A-Za-z_-]{10,}\b", "***", cleaned)
    cleaned = re.sub(r"\bAQ\.[0-9A-Za-z_-]{10,}\b", "***", cleaned)
    return cleaned
