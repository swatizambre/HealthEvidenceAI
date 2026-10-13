"""LLM provider protocol."""

from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    def complete(self, query: str, contexts: list[str]) -> str:
        """Answer using retrieved contexts only."""
        ...

    def complete_report(self, prompt: str, contexts: list[str]) -> str:
        """Phrase an evidence report from grounded contexts."""
        ...

    def score_criteria(
        self,
        *,
        criteria: list[Any],
        notes: list[Any],
        labs: list[Any],
        retrieved_hits: list[dict[str, Any]],
    ) -> list[Any]:
        """Optional clinical intelligence scoring over chart contexts."""
        ...
