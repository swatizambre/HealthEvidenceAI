"""Prepare a clinician evidence packet for a procedure checklist.

Creates or reuses an authorization case, runs the evidence review, and returns a
readiness scorecard with actionable documentation gaps. Decision-support only.

Literature-backed coaching (AMA PA surveys 2024–2025; CMS-0057-F ePA prep):
rank next documentation actions, estimate staff prep time, and flag submission
documentation risk — without approving or denying coverage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.review import review_authorization
from app.core.exceptions import AppError, NotFoundError
from app.core.safety import DISCLAIMER
from app.db.repository import get_case_by_code, get_patient_by_code, get_policy_by_code, next_public_code
from app.models import AuthorizationCase, InsurancePolicy, Patient
from app.schemas.api import (
    AuthorizationReviewRequest,
    PacketCriterionOut,
    PacketGapOut,
    PacketNextActionOut,
    PacketPrepareRequest,
    PacketPrepareResponse,
)
from app.services.cycle_time import case_cycle_minutes, stamp_prep_started
from app.services.organizations import ensure_default_organization
from app.services.specialties import normalize_specialty

# Typical staff minutes to close one gap type (coordinator/billing workflow).
_FOCUS_MINUTES = {"labs": 8, "diagnoses": 6, "meds": 5, "note": 10}
# Lower = close first (labs and diagnoses unblock most checklists).
_FOCUS_PRIORITY = {"labs": 0, "diagnoses": 1, "meds": 2, "note": 3}
_FOCUS_SPECIALTY = {
    "labs": "Laboratory",
    "diagnoses": "General medicine",
    "meds": "Pharmacy",
    "note": "General medicine",
}


def prepare_evidence_packet(session: Session, payload: PacketPrepareRequest) -> PacketPrepareResponse:
    patient = get_patient_by_code(session, payload.patient_id)
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "Patient was not found.")
    policy = get_policy_by_code(session, payload.policy_id)
    if policy is None:
        raise NotFoundError("POLICY_NOT_FOUND", "Policy was not found.")

    procedure = (payload.procedure or policy.procedure_name).strip()[:200]
    case, created = _ensure_case(session, patient, policy, procedure, payload.case_id)
    stamp_prep_started(case)
    session.flush()

    review = review_authorization(
        session,
        AuthorizationReviewRequest(
            patient_id=patient.patient_code,
            policy_id=policy.policy_code,
            procedure=procedure,
            case_id=case.case_code,
            interactive=False,
        ),
        # Domain-correct path: prepare never auto-acks clinician HITL.
        auto_complete_human_review=False,
    )

    from app.services.disorders import is_clinical_criterion_text

    criteria = [
        PacketCriterionOut(
            criterion_id=item.criterion_id,
            criterion=item.criterion,
            status=item.status,
            plain_status=_plain_status(item.status),
            reason=item.reason,
            citation_count=len(item.evidence),
        )
        for item in review.criteria
        if is_clinical_criterion_text(item.criterion)
    ]
    # Fall back to full list if filtering would empty a seeded policy mid-demo.
    if not criteria:
        criteria = [
            PacketCriterionOut(
                criterion_id=item.criterion_id,
                criterion=item.criterion,
                status=item.status,
                plain_status=_plain_status(item.status),
                reason=item.reason,
                citation_count=len(item.evidence),
            )
            for item in review.criteria
        ]
    supported = sum(1 for item in criteria if item.status == "SUPPORTED")
    gap_statuses = {"MISSING", "UNKNOWN", "NOT_SUPPORTED"}
    gap_count = sum(1 for item in criteria if item.status in gap_statuses)
    total = max(len(criteria), 1)
    readiness = int(round(100 * supported / total))

    specialties = _patient_specialties(session, patient)
    gaps: list[PacketGapOut] = []
    for label in review.missing_evidence:
        if not is_clinical_criterion_text(label):
            continue
        gaps.append(_make_gap(label, specialties, review=review))
    for item in criteria:
        if item.status in gap_statuses and not any(g.label == item.criterion for g in gaps):
            gaps.append(_make_gap(item.criterion, specialties, review=review, criterion=item))

    gaps.sort(key=lambda gap: (gap.priority, gap.label))
    next_best = _next_best_action(gaps)
    estimated_minutes = _estimate_prep_minutes(gaps, readiness)
    doc_risk, doc_risk_label = _documentation_risk(
        readiness=readiness,
        gap_count=gap_count,
        criteria=criteria,
        human_review_required=review.human_review_required,
    )
    cite_strength, cite_label = _citation_strength(criteria)

    packet_summary = _build_summary(
        patient_code=patient.patient_code,
        patient_name=patient.synthetic_name,
        procedure=procedure,
        policy_title=policy.title,
        case_code=case.case_code,
        readiness=readiness,
        coverage=review.evidence_coverage,
        criteria=criteria,
        gaps=gaps,
        specialties=specialties,
        report=review.report_summary or "",
        next_best=next_best,
        estimated_minutes=estimated_minutes,
        doc_risk_label=doc_risk_label,
        cite_label=cite_label,
        scoring_path=review.scoring_path or "",
    )

    next_steps: list[str] = []
    if next_best:
        next_steps.append(
            f"Next: {next_best.action} — {next_best.label} "
            f"(~{next_best.estimated_minutes} min under {next_best.specialty_hint})."
        )
    if gaps:
        next_steps.append(
            f"Close remaining gaps with a Visit note (~{estimated_minutes} min total staff prep estimate)."
        )
        next_steps.append("Re-run Prepare evidence pack to refresh the readiness score.")
    if review.human_review_required:
        next_steps.append("Open Reviews to acknowledge the checklist or mark needs documentation.")
    if not gaps and not review.human_review_required:
        next_steps.append(
            "Checklist looks complete for this evidence pack — still not an approval or denial."
        )
    next_steps.append("Use Open Reviews to check citations before sending for senior review.")

    cycle_mins = case_cycle_minutes(case)
    ai_brief = _build_ai_brief(
        readiness=readiness,
        gap_count=gap_count,
        scoring_path=review.scoring_path or "",
        next_best=next_best,
        human_review_required=review.human_review_required,
        doc_risk=doc_risk,
    )
    mcp_tools = _mcp_tools_from_trace(review.agent_trace or [])
    ai_drafts = sum(
        1 for gap in gaps if str(getattr(gap, "draft_source", "") or "").startswith("ai:")
    )
    from app.core.config import get_settings
    from app.services.ai_scope import describe_ai_scope

    ai_assist = {
        "scoring_path": review.scoring_path or "",
        "gap_drafts_ai": ai_drafts,
        "gap_drafts_total": len(gaps),
        "scope": describe_ai_scope(get_settings()),
    }

    return PacketPrepareResponse(
        patient_id=patient.patient_code,
        case_id=case.case_code,
        case_created=created,
        policy_id=policy.policy_code,
        policy_title=policy.title,
        procedure=procedure,
        readiness_percent=readiness,
        evidence_coverage=review.evidence_coverage,
        human_review_required=review.human_review_required,
        supported_count=supported,
        gap_count=gap_count,
        criteria=criteria,
        gaps=gaps[:12],
        specialties=specialties,
        next_best_action=next_best,
        estimated_prep_minutes=estimated_minutes,
        documentation_risk=doc_risk,
        documentation_risk_label=doc_risk_label,
        citation_strength=cite_strength,
        citation_strength_label=cite_label,
        packet_summary=packet_summary,
        next_steps=next_steps,
        report_summary=review.report_summary or "",
        run_id=review.run_id,
        scoring_path=review.scoring_path or "",
        cycle_elapsed_minutes=cycle_mins,
        agent_trace=list(review.agent_trace or []),
        ai_brief=ai_brief,
        ai_assist=ai_assist,
        mcp_tools_used=mcp_tools,
        critic_summary=review.critic_summary or "",
        documentation_pathway=list(review.documentation_pathway or []),
        pathway_summary=review.pathway_summary or "",
        readiness_scorecard=review.readiness_scorecard,
        disclaimer=DISCLAIMER,
    )


def _ensure_case(
    session: Session,
    patient: Patient,
    policy: InsurancePolicy,
    procedure: str,
    case_id: str | None,
) -> tuple[AuthorizationCase, bool]:
    if case_id:
        existing = get_case_by_code(session, case_id)
        if existing is None:
            raise NotFoundError("AUTHORIZATION_CASE_NOT_FOUND", "Authorization case was not found.")
        if existing.patient_id != patient.id or existing.policy_id != policy.id:
            raise AppError("CASE_MISMATCH", "Case does not match patient and policy.", 400)
        existing.procedure = procedure[:200]
        existing.updated_at = datetime.now(UTC)
        return existing, False

    match = session.scalar(
        select(AuthorizationCase).where(
            AuthorizationCase.patient_id == patient.id,
            AuthorizationCase.policy_id == policy.id,
        )
    )
    if match is not None:
        match.procedure = procedure[:200]
        match.updated_at = datetime.now(UTC)
        return match, False

    now = datetime.now(UTC)
    org = ensure_default_organization(session)
    case = AuthorizationCase(
        id=str(uuid4()),
        case_code=next_public_code(session, AuthorizationCase.case_code, "PA"),
        patient_id=patient.id,
        policy_id=policy.id,
        procedure=procedure[:200],
        status="queued",
        created_at=now,
        updated_at=now,
        prep_started_at=now,
        org_id=getattr(patient, "org_id", None) or org.id,
    )
    session.add(case)
    session.flush()
    return case, True


def _patient_specialties(session: Session, patient: Patient) -> list[str]:
    from app.db.repository import list_documents_for_patient

    values: list[str] = []
    seen: set[str] = set()
    for document in list_documents_for_patient(session, patient.id):
        meta = document.document_metadata or {}
        label = str(meta.get("specialty") or meta.get("department") or "").strip()
        if not label:
            continue
        specialty = normalize_specialty(label)
        if specialty not in seen and specialty not in {"Laboratory", "Pharmacy"}:
            seen.add(specialty)
            values.append(specialty)
    return values[:6]


def _plain_status(status: str) -> str:
    return {
        "SUPPORTED": "Found in chart",
        "NOT_SUPPORTED": "Doesn't match checklist",
        "MISSING": "Not found in chart",
        "UNKNOWN": "Unclear — needs clinician look",
    }.get(status, status)


def _gap_focus(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("lab", "a1c", "laboratory", "hemoglobin")):
        return "labs"
    if any(token in lower for token in ("medic", "drug", "therapy")):
        return "meds"
    if any(token in lower for token in ("imaging", "mri", "ct ", "x-ray")):
        return "note"
    if any(token in lower for token in ("diagnos", "condition")):
        return "diagnoses"
    return "note"


def _gap_action(focus: str) -> str:
    return {
        "labs": "Document lab",
        "meds": "Document medication",
        "diagnoses": "Document diagnosis",
        "note": "Add visit note",
    }.get(focus, "Add visit note")


def _make_gap(
    label: str,
    specialties: list[str],
    *,
    review: object | None = None,
    criterion: object | None = None,
) -> PacketGapOut:
    focus = _gap_focus(label)
    specialty = _FOCUS_SPECIALTY.get(focus, "General medicine")
    if focus == "note" and specialties:
        specialty = specialties[0]
    elif focus == "diagnoses" and specialties:
        specialty = specialties[0]
    snippets = _evidence_snippets_for_label(label, review=review, criterion=criterion)
    # AI drafts for high-priority gaps only (labs/diagnoses) to keep prepare snappy.
    use_llm = _FOCUS_PRIORITY.get(focus, 3) <= 1
    draft, draft_source = _draft_suggestion(label, focus, snippets, use_llm=use_llm)
    from app.services.scoring_labels import is_model_assist_source

    if is_model_assist_source(draft_source):
        agent = "AI gap coach"
    elif (draft_source or "").startswith("ai:"):
        agent = "Rule-assisted draft"
    else:
        agent = "Chart evidence"
    return PacketGapOut(
        label=label,
        focus=focus,
        action=_gap_action(focus),
        priority=_FOCUS_PRIORITY.get(focus, 3),
        estimated_minutes=_FOCUS_MINUTES.get(focus, 8),
        specialty_hint=specialty,
        draft_suggestion=draft,
        draft_source=draft_source,
        agent=agent,
        evidence_snippets=snippets[:3],
    )


def _next_best_action(gaps: list[PacketGapOut]) -> PacketNextActionOut | None:
    if not gaps:
        return None
    gap = gaps[0]
    why = {
        "labs": "Labs usually unlock numeric policy criteria first.",
        "diagnoses": "Documented conditions anchor medical-necessity language.",
        "meds": "Medication history often satisfies try-and-fail criteria.",
        "note": "A focused note closes narrative gaps reviewers look for.",
    }.get(gap.focus, "Close the highest-impact documentation gap first.")
    return PacketNextActionOut(
        label=gap.label,
        focus=gap.focus,
        action=gap.action,
        specialty_hint=gap.specialty_hint,
        estimated_minutes=gap.estimated_minutes,
        why=why,
        draft_suggestion=gap.draft_suggestion,
        draft_source=getattr(gap, "draft_source", None) or "template",
    )


def _evidence_snippets_for_label(
    label: str,
    *,
    review: object | None = None,
    criterion: object | None = None,
) -> list[str]:
    snippets: list[str] = []
    if criterion is not None:
        reason_val = getattr(criterion, "reason", None)
        if reason_val:
            reason = str(reason_val).strip()
            if reason:
                snippets.append(reason[:220])
    panel = list(getattr(review, "evidence_panel", None) or []) if review is not None else []
    needle = label.lower()[:40]
    for row in panel:
        content = str(getattr(row, "content", None) or row.get("content") if isinstance(row, dict) else "")
        content = content.strip()
        if not content:
            continue
        if needle and needle[:12] not in content.lower() and len(snippets) >= 1:
            continue
        snippets.append(content[:220])
        if len(snippets) >= 3:
            break
    return snippets


def _draft_suggestion(
    label: str,
    focus: str,
    snippets: list[str],
    *,
    use_llm: bool = True,
) -> tuple[str, str]:
    """Citation-grounded visit-note coaching — documentation readiness only."""
    from app.services.ai_assist import draft_gap_suggestion

    return draft_gap_suggestion(label, focus, snippets, use_llm=use_llm)


def _build_ai_brief(
    *,
    readiness: int,
    gap_count: int,
    scoring_path: str,
    next_best: PacketNextActionOut | None,
    human_review_required: bool,
    doc_risk: str,
) -> str:
    # Surface whether criteria were rule-scored or model-scored (local = rules).
    from app.services.scoring_labels import scoring_assist_label

    assist = scoring_assist_label(scoring_path)
    head = f"{assist} · {readiness}% ready · {gap_count} gap(s) · risk {doc_risk}."
    if next_best:
        head += f" Next: {next_best.action} — {next_best.label} (~{next_best.estimated_minutes} min)."
        if next_best.draft_suggestion:
            head += f" Draft: {next_best.draft_suggestion[:140]}"
    if human_review_required:
        head += " Senior review still required."
    return head


def _mcp_tools_from_trace(trace: list) -> list[str]:
    """Map agent nodes to the MCP tools they typically invoke."""
    mapping = {
        "load_case": "get_patient_record",
        "load_policy": "get_policy_criteria",
        "retrieve_evidence": "search_clinical_evidence",
        "evaluate_criteria": "search_clinical_evidence",
        "verify_evidence": "get_evidence_chunk",
        "human_review": "create_human_review",
        "a2a_consult": "imaging_a2a",
    }
    used: list[str] = []
    seen: set[str] = set()
    for step in trace:
        node = str(getattr(step, "node", None) or (step.get("node") if isinstance(step, dict) else "") or "")
        tool = mapping.get(node)
        if tool and tool not in seen:
            seen.add(tool)
            used.append(tool)
    if not used:
        used = ["get_patient_record", "get_policy_criteria", "search_clinical_evidence"]
    return used


def _estimate_prep_minutes(gaps: list[PacketGapOut], readiness: int) -> int:
    if not gaps:
        return 3 if readiness >= 100 else 5
    total = sum(gap.estimated_minutes for gap in gaps[:6])
    # Small overhead for re-check + handoff copy (staff PA workflow).
    return total + 4


def _documentation_risk(
    *,
    readiness: int,
    gap_count: int,
    criteria: list[PacketCriterionOut],
    human_review_required: bool,
) -> tuple[Literal["low", "moderate", "high"], str]:
    conflicts = sum(1 for item in criteria if item.status == "NOT_SUPPORTED")
    if conflicts or gap_count >= 3 or readiness < 50:
        return (
            "high",
            "High documentation risk if submitted as-is — close gaps first (not a denial).",
        )
    if gap_count >= 1 or human_review_required or readiness < 80:
        return (
            "moderate",
            "Moderate documentation risk — evidence pack incomplete or needs clinician review.",
        )
    return (
        "low",
        "Lower documentation risk for this checklist — still not an approval or coverage decision.",
    )


def _citation_strength(
    criteria: list[PacketCriterionOut],
) -> tuple[Literal["strong", "mixed", "weak"], str]:
    supported = [item for item in criteria if item.status == "SUPPORTED"]
    if not criteria:
        return "weak", "Citation strength unknown"
    if not supported:
        return "weak", "Weak citations — few or no criteria have chart sources yet"
    cited = [item for item in supported if item.citation_count > 0]
    ratio = len(cited) / max(len(supported), 1)
    avg = sum(item.citation_count for item in supported) / max(len(supported), 1)
    if ratio >= 0.9 and avg >= 1:
        return "strong", "Strong citations — supported items point to chart sources"
    if ratio >= 0.5:
        return "mixed", "Mixed citations — some supported items still lack sources"
    return "weak", "Weak citations — re-check after attaching notes or labs"


def _build_summary(
    *,
    patient_code: str,
    patient_name: str,
    procedure: str,
    policy_title: str,
    case_code: str,
    readiness: int,
    coverage: str,
    criteria: list[PacketCriterionOut],
    gaps: list[PacketGapOut],
    specialties: list[str],
    report: str,
    next_best: PacketNextActionOut | None,
    estimated_minutes: int,
    doc_risk_label: str,
    cite_label: str,
    scoring_path: str = "",
) -> str:
    from app.services.scoring_labels import scoring_method_label

    method = scoring_method_label(scoring_path)
    lines = [
        "HealthEvidence AI — Evidence pack (decision support only)",
        f"Patient: {patient_code} · {patient_name}",
        f"Case: {case_code}",
        f"Procedure: {procedure}",
        f"Policy: {policy_title}",
        f"Readiness: {readiness}% · Coverage: {coverage}",
        f"Staff prep estimate: ~{estimated_minutes} min",
        f"Documentation risk: {doc_risk_label}",
        f"Citations: {cite_label}",
        f"Prepared with: {method} + citation safety net",
    ]
    if specialties:
        lines.append(f"Specialties in file: {', '.join(specialties)}")
    if next_best:
        lines.append(
            f"Next best action: {next_best.action} — {next_best.label} "
            f"(~{next_best.estimated_minutes} min · {next_best.specialty_hint})"
        )
    lines.append("")
    lines.append("Criteria:")
    for item in criteria:
        lines.append(f"- [{item.plain_status}] {item.criterion}")
    if gaps:
        lines.append("")
        lines.append("Documentation gaps (priority order):")
        for gap in gaps:
            lines.append(
                f"- {gap.label} → {gap.action} (~{gap.estimated_minutes} min · {gap.specialty_hint})"
            )
    if report:
        lines.append("")
        lines.append("Summary:")
        lines.append(report.strip())
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
