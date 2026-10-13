"""Submission-readiness scorecard (documentation readiness — not payer approval).

Adapts competitor “denial trigger / touchless PA” ideas into a safe scorecard:
how ready is the evidence pack for *handoff*, not whether care should be approved.
"""

from __future__ import annotations

from typing import Any, Literal

RiskLevel = Literal["low", "moderate", "high"]


def build_readiness_scorecard(
    *,
    readiness_percent: int,
    criterion_results: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    documentation_risk: str,
    critic_notes: list[str] | None = None,
    cycle_elapsed_minutes: int | None = None,
    benchmark_median_minutes: float | None = None,
) -> dict[str, Any]:
    """Composite scorecard for staff desks."""
    supported = sum(
        1 for item in criterion_results if str(item.get("status") or "").upper() == "SUPPORTED"
    )
    total = max(len(criterion_results), 1)
    missing = sum(
        1
        for item in criterion_results
        if str(item.get("status") or "").upper() in {"MISSING", "UNKNOWN"}
    )
    low_conf = sum(
        1
        for item in criterion_results
        if float(item.get("confidence") or 1.0) < 0.55
        and str(item.get("status") or "").upper() == "SUPPORTED"
    )

    blockers: list[str] = []
    if contradictions:
        blockers.append(f"{len(contradictions)} conflicting note(s) to clarify")
    if missing:
        blockers.append(f"{missing} checklist item(s) still open")
    if low_conf:
        blockers.append(f"{low_conf} item(s) with thin chart support")
    if documentation_risk == "high":
        blockers.append("High chance of return for more documentation if sent as-is")

    # Ready-to-send score 0–100 (not an approval score).
    handoff = readiness_percent
    handoff -= min(30, 8 * len(contradictions))
    handoff -= min(20, 4 * low_conf)
    handoff = max(0, min(100, int(handoff)))

    level: RiskLevel = "low"
    if handoff < 55 or documentation_risk == "high" or contradictions:
        level = "high"
    elif handoff < 80 or documentation_risk == "moderate" or missing:
        level = "moderate"

    pace_note = ""
    if cycle_elapsed_minutes is not None and benchmark_median_minutes is not None:
        if cycle_elapsed_minutes > benchmark_median_minutes * 1.25:
            pace_note = (
                f"This evidence pack has been open {cycle_elapsed_minutes}m "
                f"(typical desk time ~{benchmark_median_minutes:.0f}m) — "
                "finish missing items first."
            )
        else:
            pace_note = (
                f"Open {cycle_elapsed_minutes}m so far — within the typical desk time "
                f"(~{benchmark_median_minutes:.0f}m)."
            )

    return {
        "handoff_readiness_percent": handoff,
        "checklist_supported_ratio": round(supported / total, 3),
        "supported_count": supported,
        "open_count": missing,
        "conflict_count": len(contradictions),
        "documentation_risk": level,
        "blockers": blockers[:8],
        "critic_flags": list(critic_notes or [])[:8],
        "pace_note": pace_note,
        "recommendation": _recommendation(level, blockers),
        "disclaimer": (
            "Shows how complete the paperwork looks — not a coverage decision, "
            "approval, or denial."
        ),
    }


def _recommendation(level: RiskLevel, blockers: list[str]) -> str:
    if level == "high":
        return (
            "Do not send for review yet — finish the open items, then Prepare evidence pack again. "
            + ("; ".join(blockers[:2]) if blockers else "")
        ).strip()
    if level == "moderate":
        return (
            "Evidence pack can move forward with some open items — finish the next steps, "
            "then ask a senior to review."
        )
    return (
        "Evidence pack looks ready for a senior clinician to confirm "
        "(this is not an approval)."
    )