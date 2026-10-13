"""Thin supervisor: route imaging + decide if critic warrants one re-retrieve.

Never adjudicates coverage — only chooses evidence-prep orchestration paths.
"""

from __future__ import annotations

import re
from typing import Any

_IMAGING = re.compile(
    r"\b(mri|ct|cta|pet|x-?ray|radiolog|imaging|ultrasound|sonograph|mammograph|dxa|bone\s+density)\b",
    re.I,
)
_WEAK_STATUSES = frozenset({"MISSING", "UNKNOWN", "NOT_SUPPORTED"})


def plan_orchestration(
    *,
    procedure: str,
    criteria: list[dict[str, Any]],
    a2a_enabled: bool,
) -> dict[str, Any]:
    """Decide imaging consult and retrieval strategy from procedure + criteria text."""
    blobs = [procedure or ""]
    for item in criteria:
        blobs.append(str(item.get("description") or item.get("criterion") or ""))
    joined = " ".join(blobs)
    need_imaging = bool(a2a_enabled and _IMAGING.search(joined))
    strategy = "expanded_hybrid" if criteria else "chart_only"
    return {
        "need_imaging": need_imaging,
        "retrieval_strategy": strategy,
        "reason": (
            "Imaging keywords in procedure/criteria — attach non-diagnostic imaging context"
            if need_imaging
            else "No imaging keywords — skip A2A imaging consult"
        ),
        "max_retrieve_passes": 2,
    }


def should_rereetrieve(state: dict[str, Any]) -> bool:
    """One budgeted critic→retrieve loop when open checklist items remain."""
    pass_n = int(state.get("retrieve_pass") or 0)
    max_passes = int(state.get("max_retrieve_passes") or 2)
    if pass_n >= max_passes - 1:
        return False
    results = list(state.get("criterion_results") or [])
    if any(str(item.get("status") or "").upper() in _WEAK_STATUSES for item in results):
        return True
    notes = list(state.get("critic_notes") or [])
    return any(
        token in str(note).lower()
        for note in notes
        for token in ("weak", "uncited", "thin", "missing")
    )


def open_criterion_ids(state: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in state.get("criterion_results") or []:
        if str(item.get("status") or "").upper() in _WEAK_STATUSES:
            cid = str(item.get("criterion_id") or "").strip()
            if cid:
                out.append(cid)
    return out
