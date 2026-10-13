"""Deterministic LLM double for automated tests."""

from __future__ import annotations

from typing import Any

from app.services.clinical_intelligence import grounded_rule_score
from app.services.evaluator import CriterionInput, Evaluation, LabRecord, TextRecord


class TestDoubleLLM:
    name = "test-double"

    def complete(self, query: str, contexts: list[str]) -> str:
        del query
        if not contexts:
            return "No matching synthetic documents were retrieved."
        excerpt = " ".join(contexts[0].split())
        if len(excerpt) > 320:
            excerpt = excerpt[:317] + "..."
        return f"Retrieved evidence states: {excerpt}"

    def complete_report(self, prompt: str, contexts: list[str]) -> str:
        del prompt
        if not contexts:
            return "Evidence review complete. No retrieved contexts were available for phrasing."
        excerpt = " ".join(contexts[0].split())
        if len(excerpt) > 240:
            excerpt = excerpt[:237] + "..."
        return f"Grounded evidence summary: {excerpt}"

    def score_criteria(
        self,
        *,
        criteria: list[CriterionInput],
        notes: list[TextRecord],
        labs: list[LabRecord],
        retrieved_hits: list[dict[str, Any]],
    ) -> list[Evaluation]:
        scored = grounded_rule_score(
            criteria=criteria,
            notes=notes,
            labs=labs,
            retrieved_hits=retrieved_hits,
        )
        for item in scored:
            item.reason = f"AI clinical intelligence (test-double): {item.reason}"
        return scored
