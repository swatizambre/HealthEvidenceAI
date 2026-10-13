"""Proactive AI desk insights for Today — clinician-facing, not infrastructure."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.safety import DISCLAIMER
from app.schemas.api import DeskInsightOut, DeskInsightsResponse
from app.services.disorders import is_clinical_procedure
from app.services.records import clinician_worklist

# Product-facing team names (still map to internal agent ids for ops).
_AGENT_FLEET = [
    "Care coordinator",
    "Policy checklist",
    "Chart matcher",
    "Imaging assist",
    "Evidence check",
    "Double-check",
    "Next steps",
    "Senior review",
]

_AGENT_PRODUCT = {
    "Orchestrator": "Care coordinator",
    "PolicyAgent": "Policy checklist",
    "ClinicalEvidenceAgent": "Chart matcher",
    "ImagingAgent": "Imaging assist",
    "EvidenceVerificationAgent": "Evidence check",
    "CriticAgent": "Double-check",
    "PathwayAgent": "Next steps",
    "AuthorizationAgent": "Senior review",
}


def _procedure_label(raw: str, *, policy_title: str = "") -> str:
    name = (raw or "").strip()
    title = (policy_title or "").strip()
    if name and is_clinical_procedure(name) and "catalog" not in name.lower():
        return name
    if title and "catalog" not in title.lower() and "dynamic" not in title.lower():
        return title
    return "Evidence pack"


def desk_insights(
    session: Session,
    settings: Settings | None = None,
    *,
    org_id: str | None = None,
) -> DeskInsightsResponse:
    cfg = settings or get_settings()
    worklist = clinician_worklist(session, patient_limit=4, case_limit=12, org_id=org_id)
    insights: list[DeskInsightOut] = []

    review_cases = [c for c in worklist.open_cases if c.status == "ready_for_human"]
    doc_cases = [c for c in worklist.open_cases if c.status == "needs_documentation"]
    queued = [c for c in worklist.open_cases if c.status == "queued"]

    if review_cases:
        top = review_cases[0]
        procedure = _procedure_label(top.procedure, policy_title=top.policy_title or "")
        insights.append(
            DeskInsightOut(
                insight_id="hitl-queue",
                severity="urgent",
                title=(
                    f"{len(review_cases)} evidence pack(s) waiting for a senior clinician"
                ),
                detail=(
                    f"{procedure} for {top.patient_id} — confirm the chart support "
                    "or send back for more notes."
                ),
                agent=_AGENT_PRODUCT["AuthorizationAgent"],
                patient_id=top.patient_id,
                case_id=top.case_id,
                href=f"/reviews?case={top.case_id}&queue=ready_for_human",
                cta="Open review",
            )
        )

    for item in doc_cases[:3]:
        gap = item.gap_label or item.next_hint or "Add missing chart notes"
        gap_clean = (
            gap.replace("ClinicalEvidenceAgent", "Chart matcher")
            .replace("Quality critic", "Double-check")
            .strip()
        )
        mins = item.cycle_elapsed_minutes
        aging = f" · open {mins}m" if mins is not None else ""
        procedure = _procedure_label(item.procedure, policy_title=item.policy_title or "")
        insights.append(
            DeskInsightOut(
                insight_id=f"gap-{item.case_id}",
                severity="action",
                title=f"Notes still needed for {item.patient_id}",
                detail=f"{procedure} — {gap_clean}{aging}",
                agent=_AGENT_PRODUCT["ClinicalEvidenceAgent"],
                patient_id=item.patient_id,
                case_id=item.case_id,
                href=(
                    f"/patients/{item.patient_id}?prepare=1"
                    f"&policy={item.policy_id}&case={item.case_id}"
                ),
                cta="Prepare evidence pack",
            )
        )

    if queued and not doc_cases:
        top = queued[0]
        procedure = _procedure_label(top.procedure, policy_title=top.policy_title or "")
        insights.append(
            DeskInsightOut(
                insight_id="queued-prep",
                severity="info",
                title="Evidence packs waiting to be prepared",
                detail=f"Start the evidence pack for {top.patient_id} · {procedure}",
                agent=_AGENT_PRODUCT["Orchestrator"],
                patient_id=top.patient_id,
                case_id=top.case_id,
                href=f"/patients/{top.patient_id}?prepare=1&policy={top.policy_id}",
                cta="Prepare evidence pack",
            )
        )

    if not insights:
        insights.append(
            DeskInsightOut(
                insight_id="idle",
                severity="info",
                title="Nothing urgent right now",
                detail=(
                    "No open items. Open a chart and prepare an evidence pack when you are ready."
                ),
                agent=_AGENT_PRODUCT["Orchestrator"],
                href="/patients",
                cta="Browse patients",
            )
        )

    return DeskInsightsResponse(
        insights=insights[:8],
        agent_fleet=list(_AGENT_FLEET),
        # Kept for ops/API compatibility — UI must not surface these to clinicians.
        scoring_mode=cfg.criteria_eval_mode,
        llm_provider=cfg.llm_provider,
        llm_model=cfg.model_for_provider(),
        disclaimer=DISCLAIMER,
    )
