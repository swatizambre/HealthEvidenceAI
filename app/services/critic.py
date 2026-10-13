"""CriticAgent — reflective pass over criterion scores (self-consistency).

Downgrades weakly supported claims and raises documentation confidence flags.
Never approves or denies coverage.
"""

from __future__ import annotations

from typing import Any


def calibrate_confidence(status: str, evidence_count: int, reason: str) -> float:
    """Return 0–1 confidence for a criterion outcome (documentation readiness only)."""
    status_u = (status or "").upper()
    base = {
        "SUPPORTED": 0.82,
        "NOT_SUPPORTED": 0.75,
        "MISSING": 0.9,
        "UNKNOWN": 0.45,
    }.get(status_u, 0.5)
    if status_u == "SUPPORTED":
        if evidence_count <= 0:
            return 0.25
        if evidence_count == 1:
            base -= 0.12
        elif evidence_count >= 3:
            base += 0.08
    if "uncertain" in (reason or "").lower() or "contradict" in (reason or "").lower():
        base -= 0.2
    return max(0.05, min(0.98, round(base, 2)))


def critic_reflect(criterion_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Inspect criterion results; adjust weak SUPPORTTED → UNKNOWN; attach confidence."""
    adjusted: list[dict[str, Any]] = []
    notes: list[str] = []
    weak = 0
    for raw in criterion_results:
        item = dict(raw)
        evidence = list(item.get("evidence") or [])
        status = str(item.get("status") or "UNKNOWN").upper()
        reason = str(item.get("reason") or "")
        if status == "SUPPORTED" and len(evidence) == 0:
            item["status"] = "UNKNOWN"
            item["reason"] = (
                "Double-check: marked as found but no chart citation — needs a closer look."
            )
            notes.append(f"{item.get('criterion_id')}: no chart citation found")
            weak += 1
            status = "UNKNOWN"
        elif status == "SUPPORTED" and len(evidence) == 1 and len(reason) < 24:
            item["reason"] = (
                reason + " Double-check: thin citation — confirm in the chart."
            ).strip()
            notes.append(f"{item.get('criterion_id')}: thin single citation")
            weak += 1
        conf = calibrate_confidence(status, len(evidence), str(item.get("reason") or ""))
        item["confidence"] = conf
        if conf < 0.5 and status == "SUPPORTED":
            item["status"] = "UNKNOWN"
            item["reason"] = str(item.get("reason") or "") + " Double-check: low confidence."
            notes.append(f"{item.get('criterion_id')}: low-confidence support")
            weak += 1
        adjusted.append(item)

    summary = (
        f"Double-check reviewed {len(adjusted)} checklist items; "
        f"{weak} need a closer staff look."
        if adjusted
        else "Double-check: no checklist items to review."
    )
    return {
        "criterion_results": adjusted,
        "critic_notes": notes,
        "critic_summary": summary,
        "human_review_required_boost": weak >= 2,
    }
