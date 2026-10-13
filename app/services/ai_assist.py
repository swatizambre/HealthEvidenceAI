"""Grounded AI assists for documentation readiness (never clinical decisions)."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMUnavailable
from app.core.safety import AUTONOMOUS_DECISION_VALUES, contains_unsafe_decision_language
from app.services.ai_scope import ai_assist_gap_drafts_enabled

logger = logging.getLogger("healthevidence.ai_assist")

_BANNED = re.compile(
    r"\b(approv(?:e|ed|al)|den(?:y|ied|ial)|diagnos(?:e|is|ed)|"
    r"prescrib(?:e|ed)|cover(?:ed|age)|medical\s+necessity\s+determin)\b",
    re.I,
)


def template_gap_draft(label: str, focus: str, snippets: list[str] | None = None) -> str:
    compact = label.strip()[:120]
    if focus == "labs":
        base = (
            f"Locate an existing lab for “{compact}” (name, value, unit, date) "
            "or request the result from the ordering clinician — do not invent values."
        )
    elif focus == "meds":
        base = (
            f"Locate medication documentation for “{compact}” "
            "(name, dose, status, dates) already on the chart if present."
        )
    elif focus == "diagnoses":
        base = (
            f"Find existing assessment/problem-list documentation for “{compact}” "
            "with date if already established — do not add a diagnosis only to satisfy "
            "a payer checklist."
        )
    else:
        base = (
            f"Locate existing HPI/assessment text covering “{compact}” with dates; "
            "do not invent clinical facts to close the gap."
        )
    if snippets:
        cue = snippets[0].strip().replace("\n", " ")[:160]
        if cue:
            return f"{base} Chart cue: “{cue}”"
    return base


def draft_gap_suggestion(
    label: str,
    focus: str,
    snippets: list[str],
    *,
    settings: Settings | None = None,
    use_llm: bool = True,
) -> tuple[str, str]:
    """Return (draft_text, source) where source is template | ai:<provider>."""
    cfg = settings or get_settings()
    fallback = template_gap_draft(label, focus, snippets)
    if not use_llm or not ai_assist_gap_drafts_enabled(cfg):
        return fallback, "template"

    contexts = [item.strip()[:220] for item in snippets if item and item.strip()][:3]
    if not contexts:
        contexts = [fallback]

    prompt = (
        "You assist hospital prior-auth staff finding existing documentation. "
        "Write ONE short line (max 35 words) telling staff where to look on the chart. "
        "Use only the chart cues provided. "
        "Never tell staff to record, add, or enter a new diagnosis to satisfy a checklist. "
        "Do not diagnose, approve, deny, prescribe, or invent clinical facts. "
        "Do not claim coverage or medical necessity decisions.\n"
        f"Gap label: {label.strip()[:160]}\n"
        f"Focus area: {focus}\n"
        "Return plain text only."
    )
    try:
        from app.agents.providers import build_llm

        for name in cfg.llm_provider_chain():
            try:
                provider = build_llm(cfg, name)
                raw = provider.complete_report(prompt, contexts).strip()
                cleaned = _sanitize_draft(raw) or fallback
                return cleaned[:280], f"ai:{getattr(provider, 'name', name)}"
            except (LLMUnavailable, ValueError) as exc:
                logger.debug("ai_gap_draft_provider_failed provider=%s err=%s", name, exc)
                continue
    except Exception as exc:  # noqa: BLE001 — never block prepare on assist
        logger.warning("ai_gap_draft_unavailable err=%s", str(exc)[:160])
    return fallback, "template"


def senior_review_assist(
    *,
    patient_id: str,
    case_id: str | None,
    procedure: str,
    criteria: list[dict[str, Any]],
    missing_evidence: list[str],
    contradictions: list[str],
    critic_notes: list[str],
    report_summary: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Senior HITL coaching brief — prioritizes review; never adjudicates coverage."""
    cfg = settings or get_settings()
    deterministic = _senior_review_template(
        patient_id=patient_id,
        case_id=case_id,
        procedure=procedure,
        criteria=criteria,
        missing_evidence=missing_evidence,
        contradictions=contradictions,
        critic_notes=critic_notes,
        report_summary=report_summary,
    )

    contexts = _senior_contexts(
        criteria=criteria,
        missing_evidence=missing_evidence,
        contradictions=contradictions,
        critic_notes=critic_notes,
        report_summary=report_summary,
    )
    if not ai_assist_gap_drafts_enabled(cfg):
        return {**deterministic, "source": "template"}

    prompt = (
        "You assist a senior clinician reviewing an evidence pack for prior-auth documentation. "
        "Return plain text with exactly these labeled lines:\n"
        "BRIEFING: <2 short sentences on what to verify first>\n"
        "NOTE: <one clinician desk note draft, max 40 words>\n"
        "ACTION: needs_documentation OR acknowledge_after_check\n"
        "Rules: do not approve, deny, diagnose, prescribe, or invent facts. "
        "ACTION must be desk documentation only.\n"
        f"Patient {patient_id}. Case {case_id or 'n/a'}. Procedure: {procedure}."
    )
    try:
        from app.agents.providers import build_llm

        for name in cfg.llm_provider_chain():
            try:
                provider = build_llm(cfg, name)
                raw = provider.complete_report(prompt, contexts).strip()
                parsed = _parse_senior_llm(raw, deterministic)
                if parsed:
                    parsed["source"] = f"ai:{getattr(provider, 'name', name)}"
                    return parsed
            except (LLMUnavailable, ValueError) as exc:
                logger.debug("ai_senior_review_failed provider=%s err=%s", name, exc)
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_senior_review_unavailable err=%s", str(exc)[:160])
    return {**deterministic, "source": "template"}


def _senior_contexts(
    *,
    criteria: list[dict[str, Any]],
    missing_evidence: list[str],
    contradictions: list[str],
    critic_notes: list[str],
    report_summary: str,
) -> list[str]:
    contexts: list[str] = []
    if report_summary.strip():
        contexts.append(report_summary.strip()[:400])
    for item in criteria[:12]:
        status = str(item.get("status") or "").upper()
        if status in {"SUPPORTED"}:
            continue
        reason = str(item.get("reason") or "").strip()
        label = str(item.get("criterion") or "").strip()
        contexts.append(f"{status}: {label}" + (f" — {reason}" if reason else ""))
    for gap in missing_evidence[:6]:
        contexts.append(f"Missing: {gap}")
    for conflict in contradictions[:4]:
        contexts.append(f"Conflict: {conflict}")
    for note in critic_notes[:4]:
        contexts.append(f"Critic: {note}")
    return contexts[:16] or ["No open checklist items were provided."]


def _senior_review_template(
    *,
    patient_id: str,
    case_id: str | None,
    procedure: str,
    criteria: list[dict[str, Any]],
    missing_evidence: list[str],
    contradictions: list[str],
    critic_notes: list[str],
    report_summary: str,
) -> dict[str, Any]:
    open_rows = [
        item
        for item in criteria
        if str(item.get("status") or "").upper()
        in {"MISSING", "UNKNOWN", "NOT_SUPPORTED"}
    ]
    focus_items: list[dict[str, str]] = []
    for conflict in contradictions[:3]:
        focus_items.append(
            {
                "title": "Resolve chart conflict",
                "detail": conflict[:240],
                "severity": "high",
            }
        )
    for item in open_rows[:5]:
        status = str(item.get("status") or "").upper()
        label = str(item.get("criterion") or "Checklist item").strip()
        reason = str(item.get("reason") or "").strip()
        severity = "high" if status in {"MISSING", "NOT_SUPPORTED"} else "moderate"
        focus_items.append(
            {
                "title": f"Verify: {label[:120]}",
                "detail": reason[:240]
                or f"Chart status is {status.replace('_', ' ').lower()} — confirm cited notes.",
                "severity": severity,
            }
        )
    for gap in missing_evidence[:3]:
        if any(gap.lower() in item["detail"].lower() for item in focus_items):
            continue
        focus_items.append(
            {
                "title": "Documentation still needed",
                "detail": gap[:240],
                "severity": "moderate",
            }
        )
    for note in critic_notes[:2]:
        focus_items.append(
            {
                "title": "Critic flag",
                "detail": note[:240],
                "severity": "moderate",
            }
        )

    needs_docs = bool(
        open_rows
        or missing_evidence
        or contradictions
        or any("uncited" in str(n).lower() or "weak" in str(n).lower() for n in critic_notes)
    )
    action = "needs_documentation" if needs_docs else "acknowledge_after_check"
    action_label = (
        "Send back for more notes"
        if action == "needs_documentation"
        else "Confirm checklist reviewed (after spot-check)"
    )
    top = focus_items[0]["detail"] if focus_items else "Spot-check supported items against citations."
    briefing = (
        f"Senior review assist for {patient_id}"
        + (f" / {case_id}" if case_id else "")
        + f" · {procedure}. "
        f"Start with: {top} "
        "This organizes your desk check only — not an approval or denial."
    )
    if report_summary.strip():
        briefing = f"{briefing} Pack summary cue: {report_summary.strip()[:160]}"

    if needs_docs:
        topics = [
            str(item.get("criterion") or "").strip()[:80]
            for item in open_rows[:3]
            if str(item.get("criterion") or "").strip()
        ]
        for gap in missing_evidence[:3]:
            if gap and gap not in topics:
                topics.append(gap[:80])
        note = (
            "Reviewed evidence pack. Still needs documentation on: "
            + ("; ".join(topics) if topics else "open checklist / missing chart items")
        )
    else:
        note = (
            "Reviewed evidence pack. Checklist items appear supported in chart "
            "citations; confirmed for desk handoff."
        )
    return {
        "briefing": briefing[:500],
        "focus_items": focus_items[:8],
        "suggested_clinician_note": note[:400],
        "recommended_desk_action": action,
        "recommended_desk_action_label": action_label,
    }


def _parse_senior_llm(raw: str, fallback: dict[str, Any]) -> dict[str, Any] | None:
    if not raw or contains_unsafe_decision_language(raw):
        return None
    upper = raw.upper()
    for banned in AUTONOMOUS_DECISION_VALUES:
        if banned in upper and not any(
            safe in raw.lower()
            for safe in ("not an approval", "never approve", "does not approve", "not a denial")
        ):
            # Allow product-safe refusals already handled by contains_unsafe_decision_language.
            if banned in {"APPROVE", "APPROVED", "DENY", "DENIED"}:
                continue
            return None
    briefing = fallback["briefing"]
    note = fallback["suggested_clinician_note"]
    action = fallback["recommended_desk_action"]
    found = False
    for line in raw.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("briefing:"):
            value = _sanitize_draft(stripped.split(":", 1)[1], allow_negation=True)
            if value:
                briefing = value
                found = True
        elif lower.startswith("note:"):
            value = _sanitize_draft(stripped.split(":", 1)[1], allow_negation=True)
            if value:
                note = value
                found = True
        elif lower.startswith("action:"):
            value = stripped.split(":", 1)[1].strip().lower().replace(" ", "_")
            if "need" in value and "doc" in value:
                action = "needs_documentation"
                found = True
            elif "acknowledge" in value or "confirm" in value:
                action = "acknowledge_after_check"
                found = True
    if not found:
        return None
    action_label = (
        "Send back for more notes"
        if action == "needs_documentation"
        else "Confirm checklist reviewed (after spot-check)"
    )
    return {
        "briefing": briefing[:500],
        "focus_items": fallback["focus_items"],
        "suggested_clinician_note": note[:400],
        "recommended_desk_action": action,
        "recommended_desk_action_label": action_label,
    }


def _sanitize_draft(text: str, *, allow_negation: bool = False) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    if allow_negation:
        if contains_unsafe_decision_language(cleaned):
            return ""
    else:
        upper = cleaned.upper()
        for banned in AUTONOMOUS_DECISION_VALUES:
            if banned in upper:
                return ""
        if _BANNED.search(cleaned):
            return ""
    for prefix in ("here is", "here's", "draft:", "suggestion:", "briefing:", "note:"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned.split(":", 1)[-1].strip() if ":" in cleaned[:24] else cleaned
    return cleaned[:500]
