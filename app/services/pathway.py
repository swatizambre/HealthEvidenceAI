"""Documentation pathway agent — optimal next steps before payer submission.

Inspired by competitor “guided PA path” UX, scoped to documentation readiness only
(never approve/deny/submit).
"""

from __future__ import annotations

from typing import Any


def build_documentation_pathway(
    *,
    criterion_results: list[dict[str, Any]],
    missing_evidence: list[str],
    contradictions: list[dict[str, Any]],
    documentation_risk: str = "moderate",
) -> dict[str, Any]:
    """Ordered pathway steps for staff to close the evidence pack."""
    steps: list[dict[str, Any]] = []
    order = 1

    if contradictions:
        steps.append(
            {
                "step": order,
                "title": "Resolve conflicting chart notes",
                "detail": (
                    f"{len(contradictions)} conflict(s) need a clinician to clarify "
                    "before the evidence pack is ready to send for review."
                ),
                "agent": "EvidenceVerificationAgent",
                "focus": "note",
                "priority": "urgent",
            }
        )
        order += 1

    gaps = [
        item
        for item in criterion_results
        if str(item.get("status") or "").upper() in {"MISSING", "UNKNOWN", "NOT_SUPPORTED"}
    ]
    # Prefer labs/diagnoses first (unblock most checklists) — competitor-style triage.
    def _gap_rank(item: dict[str, Any]) -> int:
        text = f"{item.get('criterion') or ''} {item.get('missing_label') or ''}".lower()
        if any(token in text for token in ("lab", "a1c", "hemoglobin", "result")):
            return 0
        if any(token in text for token in ("diagnos", "disorder", "condition")):
            return 1
        if any(token in text for token in ("medicat", "drug", "therapy")):
            return 2
        return 3

    for item in sorted(gaps, key=_gap_rank)[:6]:
        label = str(item.get("missing_label") or item.get("criterion") or "Documentation gap")
        steps.append(
            {
                "step": order,
                "title": f"Add to chart: {label[:120]}",
                "detail": str(
                    item.get("reason") or "Add a note, lab, or attachment for this checklist item."
                ),
                "agent": "ClinicalEvidenceAgent",
                "focus": "note",
                "priority": "action",
                "criterion_id": str(item.get("criterion_id") or ""),
                "confidence": item.get("confidence"),
            }
        )
        order += 1

    for label in missing_evidence[:4]:
        if any(label.lower() in str(s.get("title") or "").lower() for s in steps):
            continue
        steps.append(
            {
                "step": order,
                "title": f"Document: {label[:120]}",
                "detail": "Still needed on the chart for this checklist.",
                "agent": "PolicyAgent",
                "focus": "note",
                "priority": "action",
            }
        )
        order += 1

    steps.append(
        {
            "step": order,
            "title": "Re-check the evidence pack",
            "detail": (
                "After new notes are saved, run Prepare evidence pack again. "
                f"Current paperwork risk: {documentation_risk}. "
                "This is not a coverage decision."
            ),
            "agent": "Orchestrator",
            "focus": "packet",
            "priority": "info",
        }
    )
    order += 1
    steps.append(
        {
            "step": order,
            "title": "Senior clinician confirms",
            "detail": (
                "When the chart looks complete enough, a senior reviews the citations "
                "and confirms or sends back for more notes — never approves or denies care."
            ),
            "agent": "AuthorizationAgent",
            "focus": "review",
            "priority": "info",
        }
    )

    return {
        "pathway": steps,
        "pathway_summary": (
            f"{len(steps)} next steps to finish the paperwork "
            f"({len(gaps)} checklist item(s) still open). Guidance only — not a coverage decision."
        ),
        "gap_count": len(gaps),
    }
