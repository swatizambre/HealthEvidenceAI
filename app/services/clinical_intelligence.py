"""AI-primary clinical intelligence for criterion scoring.

Uses an LLM over retrieved chart contexts as the primary path. Deterministic
policy rules remain a safety fallback when the model is unavailable or returns
ungrounded output. Never approve/deny care.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.config import Settings
from app.core.exceptions import LLMUnavailable
from app.core.safety import AUTONOMOUS_DECISION_VALUES
from app.services.evaluator import (
    STATUS_MISSING,
    STATUS_NOT_SUPPORTED,
    STATUS_SUPPORTED,
    STATUS_UNKNOWN,
    CriterionInput,
    Evaluation,
    EvidenceItem,
    LabRecord,
    TextRecord,
    evaluate_criteria,
)
from app.services.safety_net import apply_safety_net

logger = logging.getLogger("healthevidence.clinical_intelligence")

_STATUSES = frozenset(
    {STATUS_SUPPORTED, STATUS_NOT_SUPPORTED, STATUS_MISSING, STATUS_UNKNOWN}
)
_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def score_criteria_clinical(
    settings: Settings,
    criteria: list[CriterionInput],
    notes: list[TextRecord],
    labs: list[LabRecord],
    retrieved_hits: list[dict[str, Any]] | None = None,
) -> tuple[list[Evaluation], str]:
    """Return (evaluations, scoring_path). Primary path is AI when configured."""
    mode = settings.criteria_eval_mode.strip().lower()
    if mode in {"rules", "deterministic", "rule"}:
        return apply_safety_net(evaluate_criteria(criteria, notes, labs)), "rules"

    errors: list[str] = []
    from app.agents.providers import build_llm

    for name in settings.llm_provider_chain():
        try:
            provider = build_llm(settings, name)
            scored = _score_with_provider(
                provider,
                criteria=criteria,
                notes=notes,
                labs=labs,
                retrieved_hits=retrieved_hits or [],
            )
            cleaned = apply_safety_net(scored)
            provider_name = str(getattr(provider, "name", name) or name).strip().lower()
            # Local provider runs the rule engine only — do not label it as an AI path.
            if provider_name == "local":
                path = "rule_check:local"
            else:
                path = f"ai_clinical:{provider_name}"
            logger.info("clinical_intelligence_scored path=%s criteria=%s", path, len(cleaned))
            return cleaned, path
        except (LLMUnavailable, ValueError, json.JSONDecodeError) as exc:
            message = getattr(exc, "message", str(exc))
            errors.append(f"{name}: {message}")
            continue

    fallback = apply_safety_net(evaluate_criteria(criteria, notes, labs))
    logger.warning(
        "clinical_intelligence_fallback_rules errors=%s",
        " | ".join(errors[:3]) if errors else "none",
    )
    return fallback, "rules_fallback"


def _score_with_provider(
    provider: object,
    *,
    criteria: list[CriterionInput],
    notes: list[TextRecord],
    labs: list[LabRecord],
    retrieved_hits: list[dict[str, Any]],
) -> list[Evaluation]:
    score_fn = getattr(provider, "score_criteria", None)
    if callable(score_fn):
        return score_fn(
            criteria=criteria,
            notes=notes,
            labs=labs,
            retrieved_hits=retrieved_hits,
        )
    return _score_via_complete(
        provider,
        criteria=criteria,
        notes=notes,
        labs=labs,
        retrieved_hits=retrieved_hits,
    )


def _score_via_complete(
    provider: object,
    *,
    criteria: list[CriterionInput],
    notes: list[TextRecord],
    labs: list[LabRecord],
    retrieved_hits: list[dict[str, Any]],
) -> list[Evaluation]:
    contexts = _build_contexts(notes, labs, retrieved_hits)
    catalog = _evidence_catalog(notes, labs, retrieved_hits)
    prompt = _clinical_prompt(criteria, catalog)
    complete = getattr(provider, "complete", None)
    if not callable(complete):
        raise LLMUnavailable("Provider cannot complete clinical scoring.")
    raw = complete(prompt, contexts)
    payload = _parse_json(raw)
    return _evaluations_from_payload(payload, criteria, catalog)


def grounded_rule_score(
    *,
    criteria: list[CriterionInput],
    notes: list[TextRecord],
    labs: list[LabRecord],
    retrieved_hits: list[dict[str, Any]] | None = None,
) -> list[Evaluation]:
    """Local / test-double grounded scorer: rule engine over source text."""
    del retrieved_hits
    return evaluate_criteria(criteria, notes, labs)


def _clinical_prompt(criteria: list[CriterionInput], catalog: list[dict[str, str]]) -> str:
    criterion_lines = [
        f"- id={item.code} | {item.description}" for item in criteria
    ]
    cite_lines = [
        f"- cite_id={entry['cite_id']} doc={entry['document_id']} chunk={entry['chunk_id']}: "
        f"{entry['text'][:220]}"
        for entry in catalog[:40]
    ]
    return (
        "CLINICAL_CRITERION_EVAL\n"
        "You are a clinical evidence intelligence assistant for SYNTHETIC prior-auth prep.\n"
        "Score each policy criterion using ONLY the provided chart excerpts.\n"
        "Allowed statuses: SUPPORTED, NOT_SUPPORTED, MISSING, UNKNOWN.\n"
        "For SUPPORTED or NOT_SUPPORTED you MUST include cite_ids from the catalog.\n"
        "If evidence is absent, use MISSING. If conflicting/unclear, use UNKNOWN.\n"
        "Do NOT diagnose, prescribe, APPROVE, or DENY care.\n"
        "Return JSON only with shape:\n"
        '{"criteria":[{"criterion_id":"...","status":"SUPPORTED|NOT_SUPPORTED|MISSING|UNKNOWN",'
        '"reason":"...","cite_ids":["..."],"missing_label":"...optional"}]}\n\n'
        "Criteria:\n"
        + "\n".join(criterion_lines)
        + "\n\nCitation catalog:\n"
        + ("\n".join(cite_lines) if cite_lines else "(none)")
    )


def _build_contexts(
    notes: list[TextRecord],
    labs: list[LabRecord],
    retrieved_hits: list[dict[str, Any]],
) -> list[str]:
    contexts: list[str] = []
    for note in notes[:6]:
        contexts.append(f"NOTE {note.document_id}: {note.content[:900]}")
    for lab in labs[:8]:
        contexts.append(f"LAB {lab.document_id} {lab.test_name}: {lab.content[:400]}")
    for hit in retrieved_hits[:12]:
        contexts.append(
            f"RETRIEVED {hit.get('document_id')} {hit.get('chunk_id')}: "
            f"{str(hit.get('labeled_content') or hit.get('content') or '')[:500]}"
        )
    return contexts


def _evidence_catalog(
    notes: list[TextRecord],
    labs: list[LabRecord],
    retrieved_hits: list[dict[str, Any]],
) -> list[dict[str, str]]:
    catalog: list[dict[str, str]] = []
    index = 1
    for note in notes:
        for chunk_id, text in note.chunks:
            catalog.append(
                {
                    "cite_id": f"C{index}",
                    "document_id": note.document_id,
                    "chunk_id": chunk_id,
                    "source": note.source,
                    "text": text[:400],
                }
            )
            index += 1
    for lab in labs:
        for chunk_id, text in lab.chunks:
            catalog.append(
                {
                    "cite_id": f"C{index}",
                    "document_id": lab.document_id,
                    "chunk_id": chunk_id,
                    "source": "lab_result",
                    "text": text[:400],
                }
            )
            index += 1
    for hit in retrieved_hits:
        document_id = str(hit.get("document_id") or "")
        chunk_id = str(hit.get("chunk_id") or "")
        text = str(hit.get("labeled_content") or hit.get("content") or "")[:400]
        if not document_id or not chunk_id or not text:
            continue
        catalog.append(
            {
                "cite_id": f"C{index}",
                "document_id": document_id,
                "chunk_id": chunk_id,
                "source": str(hit.get("source") or "retrieved"),
                "text": text,
            }
        )
        index += 1
    return catalog


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Clinical intelligence response must be a JSON object.")
    return payload


def _evaluations_from_payload(
    payload: dict[str, Any],
    criteria: list[CriterionInput],
    catalog: list[dict[str, str]],
) -> list[Evaluation]:
    by_cite = {entry["cite_id"]: entry for entry in catalog}
    rows = payload.get("criteria")
    if not isinstance(rows, list):
        raise ValueError("Clinical intelligence JSON missing criteria list.")
    by_id = {
        str(row.get("criterion_id") or ""): row
        for row in rows
        if isinstance(row, dict)
    }
    results: list[Evaluation] = []
    for criterion in criteria:
        row = by_id.get(criterion.code) or {}
        status = str(row.get("status") or STATUS_UNKNOWN).upper()
        if status not in _STATUSES:
            status = STATUS_UNKNOWN
        reason = str(row.get("reason") or "").strip() or (
            "Model checked the chart excerpts for this checklist item."
        )
        if any(token in reason.upper() for token in AUTONOMOUS_DECISION_VALUES):
            reason = "Model summarized chart support without making a care decision."
        cite_ids = row.get("cite_ids") or row.get("citations") or []
        evidence: list[EvidenceItem] = []
        if isinstance(cite_ids, list):
            for cite_id in cite_ids:
                entry = by_cite.get(str(cite_id))
                if entry is None:
                    continue
                evidence.append(
                    EvidenceItem(
                        document_id=entry["document_id"],
                        chunk_id=entry["chunk_id"],
                        source=entry["source"],
                        text_reference=entry["text"],
                    )
                )
        missing_label = None
        if status == STATUS_MISSING:
            missing_label = str(row.get("missing_label") or criterion.description)
        results.append(
            Evaluation(
                criterion_id=criterion.code,
                criterion=criterion.description,
                status=status,
                evidence=evidence,
                reason=f"AI check: {reason}",
                missing_label=missing_label,
            )
        )
    return results
