"""India cashless pre-authorization (TPA) desk — stage machine, clocks, worklist, workspace.

Binding contract: docs/TPA_DESK_CONTRACT.md. The desk prepares paperwork; a senior
clinician confirms via the existing HITL review; staff send through the insurer/TPA
portal and record here what the insurer/TPA did. Nothing here approves, denies or
submits anything to an insurer.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, NotFoundError
from app.db.repository import get_case_by_code, next_public_code
from app.models import AuditEvent, AuthorizationCase, CaseQuery, InsurancePolicy, Patient
from app.services.audit import record_audit
from app.services.case_checklist import (
    ReadinessSummary,
    build_case_checklist,
    summarize_readiness,
)

DESK_DISCLAIMER = (
    "Prepares cashless pre-authorization paperwork for a senior clinician to confirm. "
    "It does not approve, deny, or submit anything to an insurer or TPA — staff send "
    "through the insurer/TPA portal and record here what happened. Not a medical device."
)

STAGES: tuple[str, ...] = (
    "draft",
    "ready_to_send",
    "sent",
    "query",
    "approved",
    "enhancement",
    "discharge_pending",
    "discharge_sent",
    "closed",
)
STAGE_LABELS: dict[str, str] = {
    "draft": "Preparing request",
    "ready_to_send": "Ready to send",
    "sent": "Sent — awaiting insurer",
    "query": "TPA query",
    "approved": "Insurer approval recorded",
    "enhancement": "Enhancement requested",
    "discharge_pending": "Discharge in progress",
    "discharge_sent": "Final approval awaited",
    "closed": "Closed",
}
PAYER_TYPES: tuple[str, ...] = ("insurer", "tpa", "pmjay", "cghs", "self_pay")
ADMISSION_TYPES: tuple[str, ...] = ("planned", "emergency")

# action -> stages it may be applied from.
TRANSITIONS: dict[str, frozenset[str]] = {
    "mark_sent": frozenset({"draft", "ready_to_send"}),
    "record_query": frozenset({"sent", "query", "enhancement", "discharge_sent"}),
    "answer_query": frozenset({"query"}),
    "record_approval": frozenset({"sent", "enhancement"}),
    "request_enhancement": frozenset({"approved"}),
    "start_discharge": frozenset({"approved"}),
    "mark_discharge_sent": frozenset({"discharge_pending"}),
    "close": frozenset({"draft", "ready_to_send", "approved", "discharge_sent"}),
}

# IRDAI master circular (2024): pre-auth decision within 1 hour, final discharge
# authorization within 3 hours. Desk default for answering a query: 24 hours.
INSURER_DECISION_HOURS = 1
FINAL_APPROVAL_HOURS = 3
QUERY_RESPONSE_DEFAULT_HOURS = 24

# Editable case fields (PATCH / create) — never stage or clock fields.
EDITABLE_FIELDS: tuple[str, ...] = (
    "payer_type",
    "insurer_name",
    "tpa_name",
    "policy_number",
    "admission_type",
    "admitted_at",
    "expected_discharge_at",
    "treating_doctor",
    "provisional_diagnosis",
    "icd10_code",
    "proposed_treatment",
    "estimated_cost_inr",
    "cost_breakdown_inr",
    "form_extra",
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; every stored time is UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    stamp = aware(value)
    return stamp.isoformat() if stamp is not None else None


def stage_of(case: AuthorizationCase) -> str:
    value = str(getattr(case, "stage", "") or "draft")
    return value if value in STAGES else "draft"


def mask_policy(number: str | None) -> str:
    digits = str(number or "").strip()
    return digits[-4:] if digits else ""


def age_years(birth: date | None, *, today: date | None = None) -> int | None:
    if birth is None:
        return None
    ref = today or now_utc().date()
    return ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))


# --------------------------------------------------------------------------- queries


def list_queries(session: Session, case: AuthorizationCase) -> list[CaseQuery]:
    return list(
        session.scalars(
            select(CaseQuery)
            .where(CaseQuery.case_id == case.id)
            .order_by(CaseQuery.raised_at, CaseQuery.query_code)
        ).all()
    )


def open_queries(queries: list[CaseQuery]) -> list[CaseQuery]:
    return [item for item in queries if item.responded_at is None]


def query_dict(item: CaseQuery) -> dict[str, Any]:
    return {
        "query_id": item.query_code,
        "raised_at": iso(item.raised_at),
        "text": item.text or "",
        "response_due_at": iso(item.response_due_at),
        "responded_at": iso(item.responded_at),
        "response": item.response or "",
        "raised_by": item.raised_by or "",
        "responded_by": item.responded_by or "",
    }


# --------------------------------------------------------------------------- clocks


def _clock(kind: str, label: str, due: datetime | None, now: datetime) -> dict[str, Any]:
    due_aware = aware(due)
    if due_aware is None:
        return {"kind": "none" if kind == "none" else kind, "label": label, "due_at": None,
                "minutes_left": None, "overdue": False}
    minutes_left = math.floor((due_aware - now).total_seconds() / 60.0)
    return {
        "kind": kind,
        "label": label,
        "due_at": due_aware.isoformat(),
        "minutes_left": minutes_left,
        "overdue": minutes_left < 0,
    }


def _prep_sla_minutes() -> int:
    from app.core.config import get_settings

    return max(15, int(get_settings().packet_sla_minutes or 240))


def compute_clock(
    case: AuthorizationCase,
    queries: list[CaseQuery],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The one clock that matters for this case right now."""
    current = now or now_utc()
    stage = stage_of(case)
    if stage == "query":
        pending = [item for item in open_queries(queries) if item.response_due_at is not None]
        if pending:
            first = min(pending, key=lambda item: aware(item.response_due_at) or current)
            return _clock("query_response", "Reply to TPA query", first.response_due_at, current)
        return _clock("query_response", "Reply to TPA query", None, current)
    if stage == "sent":
        return _clock("insurer_decision", "Insurer decision due", case.decision_due_at, current)
    if stage == "enhancement":
        return _clock(
            "insurer_decision", "Enhancement decision due", case.decision_due_at, current
        )
    if stage == "discharge_sent":
        return _clock("final_approval", "Final approval due", case.final_due_at, current)
    if stage in {"draft", "ready_to_send"}:
        start = aware(case.prep_started_at) or aware(case.created_at)
        due = start + timedelta(minutes=_prep_sla_minutes()) if start is not None else None
        label = "Send to insurer" if stage == "ready_to_send" else "Prepare pre-auth request"
        return _clock("prep", label, due, current)
    if stage == "discharge_pending":
        return _clock(
            "prep", "Prepare discharge request", case.expected_discharge_at, current
        )
    return _clock("none", "No clock running", None, current)


def urgency_key(clock: Mapping[str, Any], created_at: datetime | None) -> tuple[int, float, str]:
    """Overdue first, then smallest minutes_left, then oldest."""
    overdue = bool(clock.get("overdue"))
    minutes = clock.get("minutes_left")
    created = iso(created_at) or ""
    return (0 if overdue else 1, float(minutes) if minutes is not None else math.inf, created)


# --------------------------------------------------------------------------- review


@dataclass(frozen=True)
class ReviewState:
    state: str
    by_label: str = ""
    at: str | None = None
    notes: str = ""
    run_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "by_label": self.by_label,
            "at": self.at,
            "notes": self.notes,
            "run_id": self.run_id,
        }


def _reviewer_notes(reason: str) -> str:
    match = re.search(r"reviewer=(.*)$", reason or "")
    return match.group(1).strip()[:500] if match else ""


def review_state(session: Session, case: AuthorizationCase) -> ReviewState:
    """Senior HITL state from the latest review run (recorded by the existing resume path)."""
    run_state: dict[str, Any] | None = None
    run_id = str(case.last_run_id or "").strip()
    if run_id:
        from app.agents.runs import load_run

        run_state = load_run(run_id, session)
    state = "not_started"
    notes = ""
    if run_state:
        decision = str(run_state.get("human_decision") or "")
        notes = _reviewer_notes(str(run_state.get("human_review_reason") or ""))
        if decision == "acknowledged":
            state = "acknowledged"
        elif decision == "needs_documentation":
            state = "needs_documentation"
        elif run_state.get("paused") or run_state.get("status") == "awaiting_human_review":
            state = "awaiting_senior"
    if state == "not_started":
        legacy = str(case.status or "")
        if legacy == "ready_for_human":
            state = "awaiting_senior"
        elif legacy == "needs_documentation" and run_state is None:
            state = "needs_documentation"
    if state == "awaiting_senior":
        return ReviewState(state=state, at=iso(case.review_ready_at), run_id=run_id)
    if state in {"acknowledged", "needs_documentation"}:
        event = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.action == "evidence_pack_review",
                AuditEvent.resource_type == "authorization_case",
                AuditEvent.resource_id == case.case_code,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
        if event is not None:
            return ReviewState(
                state=state,
                by_label=event.actor,
                at=iso(event.created_at),
                notes=notes,
                run_id=run_id,
            )
        return ReviewState(state=state, notes=notes, run_id=run_id)
    return ReviewState(state=state, run_id=run_id)


def on_review_decision(
    session: Session,
    case_code: str | None,
    *,
    decision: str | None,
    awaiting: bool,
) -> None:
    """Keep the desk stage in step with senior HITL (called from the review lifecycle sync)."""
    if not case_code:
        return
    case = get_case_by_code(session, case_code)
    if case is None or not str(case.payer_type or "").strip():
        return
    stage = stage_of(case)
    if decision == "acknowledged" and not awaiting and stage == "draft":
        case.stage = "ready_to_send"
    elif (decision == "needs_documentation" or awaiting) and stage == "ready_to_send":
        case.stage = "draft"
    session.flush()


# --------------------------------------------------------------------------- serializers


def patient_brief(patient: Patient | None) -> dict[str, Any]:
    if patient is None:
        return {"patient_id": "", "name": "", "mrn": "", "age": None, "sex": ""}
    return {
        "patient_id": patient.patient_code,
        "name": patient.synthetic_name,
        "mrn": patient.patient_code,
        "age": age_years(patient.birth_date),
        "sex": patient.sex,
    }


def case_dict(
    case: AuthorizationCase,
    *,
    clock: Mapping[str, Any],
    policy: InsurancePolicy | None,
    patient: Patient | None,
) -> dict[str, Any]:
    stage = stage_of(case)
    return {
        "case_id": case.case_code,
        "patient_id": patient.patient_code if patient is not None else "",
        "policy_id": policy.policy_code if policy is not None else "",
        "checklist_title": policy.title if policy is not None else "",
        "procedure": case.procedure,
        "payer_type": case.payer_type,
        "insurer_name": case.insurer_name or "",
        "tpa_name": case.tpa_name or "",
        "policy_number": case.policy_number or "",
        "policy_last4": mask_policy(case.policy_number),
        "admission_type": case.admission_type or "planned",
        "admitted_at": iso(case.admitted_at),
        "expected_discharge_at": iso(case.expected_discharge_at),
        "treating_doctor": case.treating_doctor or "",
        "provisional_diagnosis": case.provisional_diagnosis or "",
        "icd10_code": case.icd10_code or "",
        "proposed_treatment": case.proposed_treatment or case.procedure or "",
        "estimated_cost_inr": case.estimated_cost_inr,
        "approved_amount_inr": case.approved_amount_inr,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "clock": dict(clock),
        "sent_at": iso(case.sent_at),
        "decision_due_at": iso(case.decision_due_at),
        "approved_at": iso(case.approved_at),
        "discharge_requested_at": iso(case.discharge_requested_at),
        "final_due_at": iso(case.final_due_at),
        "revised_estimate_inr": case.revised_estimate_inr,
        "enhancement_reason": case.enhancement_reason or "",
        "enhancement_requested_at": iso(case.enhancement_requested_at),
        "enhancement_count": int(case.enhancement_count or 0),
        "discharge_override_reason": case.discharge_override_reason or "",
        "closed_at": iso(case.closed_at),
        "cost_breakdown_inr": dict(case.cost_breakdown_inr or {}),
        "form_extra": dict(case.form_extra or {}),
        "assigned_to": case.assigned_to,
        "last_run_id": case.last_run_id,
        "created_at": iso(case.created_at),
        "updated_at": iso(case.updated_at),
    }


# --------------------------------------------------------------------------- timeline

_AUDIT_TIMELINE = {
    "evidence_pack_prepare": "Evidence pack prepared",
    "evidence_pack_review": "Senior review recorded",
    "case_assign": "Case assigned",
    "desk_case_create": "Case opened on the desk",
    "desk_case_update": "Case details updated",
}


def build_timeline(
    session: Session, case: AuthorizationCase, queries: list[CaseQuery]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(at: datetime | None, event: str, actor: str = "Desk") -> None:
        stamp = iso(at)
        if stamp:
            events.append({"at": stamp, "event": event, "actor_label": actor})

    add(case.created_at, "Case opened")
    add(case.admitted_at, f"Admitted ({case.admission_type or 'planned'})")
    add(case.sent_at, "Pre-auth request sent via insurer/TPA portal")
    for item in queries:
        add(item.raised_at, f"Query received ({item.query_code})", item.raised_by or "Insurer/TPA")
        add(item.responded_at, f"Query answered ({item.query_code})", item.responded_by or "Desk")
    if case.approved_amount_inr is not None:
        add(case.approved_at, f"Approval recorded: ₹{format_inr(case.approved_amount_inr)}")
    add(case.enhancement_requested_at, "Enhancement requested")
    add(case.discharge_requested_at, "Discharge request sent")
    add(case.closed_at, "Case closed")
    rows = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.resource_type == "authorization_case",
            AuditEvent.resource_id == case.case_code,
            AuditEvent.action.in_(list(_AUDIT_TIMELINE)),
        )
        .order_by(AuditEvent.created_at)
        .limit(100)
    ).all()
    for row in rows:
        label = _AUDIT_TIMELINE.get(row.action, row.action)
        if row.action == "evidence_pack_review":
            decision = "needs_documentation" if "needs_documentation" in (row.detail or "") else ""
            label = (
                "Senior sent back for documentation" if decision else "Senior acknowledged checklist"
            )
        add(row.created_at, label, row.actor)
    events.sort(key=lambda item: item["at"])
    return events


def format_inr(amount: int | None) -> str:
    """Indian digit grouping: 125000 -> 1,25,000."""
    if amount is None:
        return ""
    negative = amount < 0
    digits = str(abs(int(amount)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"-{digits}" if negative else digits


# --------------------------------------------------------------------------- workspace


def require_case(session: Session, case_code: str) -> AuthorizationCase:
    case = get_case_by_code(session, case_code)
    if case is None:
        raise NotFoundError("CASE_NOT_FOUND", "Authorization case was not found.")
    return case


def case_patient(session: Session, case: AuthorizationCase) -> Patient | None:
    return session.get(Patient, case.patient_id)


def build_workspace(
    session: Session, case: AuthorizationCase, *, now: datetime | None = None
) -> dict[str, Any]:
    current = now or now_utc()
    patient = case_patient(session, case)
    policy = session.get(InsurancePolicy, case.policy_id)
    queries = list_queries(session, case)
    clock = compute_clock(case, queries, now=current)
    checklist = build_case_checklist(session, case)
    readiness: ReadinessSummary = summarize_readiness(checklist)
    return {
        "case": case_dict(case, clock=clock, policy=policy, patient=patient),
        "patient": patient_brief(patient),
        "readiness": readiness.as_dict(),
        "checklist": [item.as_dict() for item in checklist],
        "queries": [query_dict(item) for item in queries],
        "timeline": build_timeline(session, case, queries),
        "review": review_state(session, case).as_dict(),
        "payer_label": "Illustrative checklist — confirm with each insurer/TPA",
        "disclaimer": DESK_DISCLAIMER,
    }


# --------------------------------------------------------------------------- worklist


def _desk_rows(
    session: Session, *, org_id: str | None
) -> list[tuple[AuthorizationCase, Patient]]:
    statement = (
        select(AuthorizationCase, Patient)
        .join(Patient, AuthorizationCase.patient_id == Patient.id)
        .where(AuthorizationCase.payer_type.is_not(None))
        .where(AuthorizationCase.payer_type != "")
        .order_by(AuthorizationCase.case_code)
    )
    if org_id:
        statement = statement.where(Patient.org_id == org_id)
    return [(row[0], row[1]) for row in session.execute(statement).all()]


def _matches(case: AuthorizationCase, patient: Patient, q: str) -> bool:
    needle = q.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        str(value or "")
        for value in (
            case.case_code,
            patient.patient_code,
            patient.synthetic_name,
            case.insurer_name,
            case.tpa_name,
            case.proposed_treatment,
            case.procedure,
            case.provisional_diagnosis,
        )
    ).lower()
    return needle in haystack


def _queries_by_case(session: Session, case_ids: list[str]) -> dict[str, list[CaseQuery]]:
    if not case_ids:
        return {}
    grouped: dict[str, list[CaseQuery]] = {}
    for row in session.scalars(select(CaseQuery).where(CaseQuery.case_id.in_(case_ids))).all():
        grouped.setdefault(row.case_id, []).append(row)
    return grouped


def desk_worklist(
    session: Session,
    *,
    org_id: str | None = None,
    stage: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or now_utc()
    rows = _desk_rows(session, org_id=org_id)
    queries = _queries_by_case(session, [case.id for case, _patient in rows])
    clocks = {case.id: compute_clock(case, queries.get(case.id, []), now=current) for case, _ in rows}

    counts: dict[str, int] = {name: 0 for name in STAGES}
    counts["overdue"] = 0
    for case, _patient in rows:
        counts[stage_of(case)] += 1
        if clocks[case.id]["overdue"]:
            counts["overdue"] += 1

    wanted_stage = (stage or "").strip()
    if wanted_stage and wanted_stage not in STAGES and wanted_stage != "overdue":
        raise AppError("VALIDATION_ERROR", f"Unknown stage filter: {wanted_stage}.", 422)
    filtered = [
        (case, patient)
        for case, patient in rows
        if (
            not wanted_stage
            or (wanted_stage == "overdue" and clocks[case.id]["overdue"])
            or stage_of(case) == wanted_stage
        )
        and _matches(case, patient, q or "")
    ]
    filtered.sort(key=lambda row: urgency_key(clocks[row[0].id], row[0].created_at))
    page = filtered[offset : offset + limit]
    items: list[dict[str, Any]] = []
    for case, patient in page:
        readiness = summarize_readiness(build_case_checklist(session, case))
        stage_value = stage_of(case)
        items.append(
            {
                "case_id": case.case_code,
                "patient_id": patient.patient_code,
                "patient_name": patient.synthetic_name,
                "mrn": patient.patient_code,
                "age": age_years(patient.birth_date),
                "sex": patient.sex,
                "payer_type": case.payer_type,
                "insurer_name": case.insurer_name or "",
                "tpa_name": case.tpa_name or "",
                "policy_last4": mask_policy(case.policy_number),
                "proposed_treatment": case.proposed_treatment or case.procedure or "",
                "estimated_cost_inr": case.estimated_cost_inr,
                "approved_amount_inr": case.approved_amount_inr,
                "stage": stage_value,
                "stage_label": STAGE_LABELS[stage_value],
                "readiness_percent": readiness.percent,
                "readiness_label": readiness.label,
                "open_items": readiness.open_items,
                "open_queries": len(open_queries(queries.get(case.id, []))),
                "clock": clocks[case.id],
                "assigned_to": case.assigned_to,
                "updated_at": iso(case.updated_at),
            }
        )
    return {"items": items, "total": len(filtered), "counts": counts}


def desk_stats(
    session: Session, *, org_id: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    current = now or now_utc()
    rows = _desk_rows(session, org_id=org_id)
    queries = _queries_by_case(session, [case.id for case, _patient in rows])
    overdue = due_soon = queries_open = ready = awaiting = 0
    for case, _patient in rows:
        case_queries = queries.get(case.id, [])
        clock = compute_clock(case, case_queries, now=current)
        if clock["overdue"]:
            overdue += 1
        elif clock["minutes_left"] is not None and clock["minutes_left"] <= 60:
            due_soon += 1
        queries_open += len(open_queries(case_queries))
        stage = stage_of(case)
        if stage == "ready_to_send":
            ready += 1
        if stage in {"draft", "ready_to_send"} and review_state(session, case).state == (
            "awaiting_senior"
        ):
            awaiting += 1
    from app.services.cycle_time import packet_ops_metrics

    median = packet_ops_metrics(session, org_id=org_id).get("median_minutes")
    return {
        "overdue": overdue,
        "due_within_60m": due_soon,
        "queries_open": queries_open,
        "ready_to_send": ready,
        "awaiting_senior": awaiting,
        "median_prep_minutes": int(round(float(median))) if isinstance(median, int | float) else None,
        "total_cases": len(rows),
    }


# --------------------------------------------------------------------------- writes


def _validate_choice(value: Any, allowed: tuple[str, ...], name: str) -> None:
    if value is not None and value not in allowed:
        raise AppError(
            "VALIDATION_ERROR", f"{name} must be one of: {', '.join(allowed)}.", 422
        )


def _apply_fields(case: AuthorizationCase, values: Mapping[str, Any]) -> list[str]:
    changed: list[str] = []
    for name in EDITABLE_FIELDS:
        if name not in values:
            continue
        value = values[name]
        if name == "payer_type":
            if value is None:
                raise AppError("VALIDATION_ERROR", "payer_type cannot be cleared.", 422)
            _validate_choice(value, PAYER_TYPES, "payer_type")
        elif name == "admission_type":
            _validate_choice(value, ADMISSION_TYPES, "admission_type")
            value = value or "planned"
        elif name in {"cost_breakdown_inr", "form_extra"}:
            merged = dict(getattr(case, name) or {})
            for key, item in dict(value or {}).items():
                if item is None:
                    merged.pop(str(key), None)
                else:
                    merged[str(key)] = item
            value = merged
        elif name == "icd10_code" and isinstance(value, str):
            value = value.strip().upper()
        elif isinstance(value, str):
            value = value.strip()
        elif value is None and name not in {
            "admitted_at",
            "expected_discharge_at",
            "estimated_cost_inr",
        }:
            value = ""
        setattr(case, name, value)
        changed.append(name)
    if "proposed_treatment" in changed and case.proposed_treatment:
        case.procedure = str(case.proposed_treatment)[:200]
    return changed


def create_case(
    session: Session,
    values: Mapping[str, Any],
    *,
    actor: str,
    now: datetime | None = None,
) -> AuthorizationCase:
    from app.db.repository import get_patient_by_code, get_policy_by_code
    from app.services.organizations import ensure_default_organization

    current = now or now_utc()
    patient = get_patient_by_code(session, str(values.get("patient_id") or ""))
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "Patient was not found.")
    policy_code = str(values.get("policy_id") or "").strip()
    policy = (
        get_policy_by_code(session, policy_code)
        if policy_code
        else match_checklist(session, str(values.get("proposed_treatment") or ""))
    )
    if policy is None:
        raise NotFoundError("POLICY_NOT_FOUND", "Checklist policy was not found.")
    treatment = str(values.get("proposed_treatment") or policy.procedure_name).strip()
    case = AuthorizationCase(
        id=str(uuid4()),
        case_code=next_public_code(session, AuthorizationCase.case_code, "PA"),
        patient_id=patient.id,
        policy_id=policy.id,
        procedure=treatment[:200],
        status="queued",
        created_at=current,
        updated_at=current,
        prep_started_at=current,
        org_id=patient.org_id or ensure_default_organization(session).id,
        stage="draft",
        enhancement_count=0,
        cost_breakdown_inr={},
        form_extra={},
    )
    _apply_fields(case, {key: values[key] for key in EDITABLE_FIELDS if key in values})
    if not case.payer_type:
        raise AppError("VALIDATION_ERROR", "payer_type is required.", 422)
    session.add(case)
    session.flush()
    record_audit(
        session,
        action="desk_case_create",
        actor=actor[:64],
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
        detail=f"patient={patient.patient_code};policy={policy.policy_code};payer={case.payer_type}",
    )
    return case


def match_checklist(session: Session, treatment: str) -> InsurancePolicy | None:
    """Pick the illustrative India checklist whose keywords match the treatment text."""
    from app.services.tpa_seed import checklist_for_treatment

    code = checklist_for_treatment(treatment)
    if code:
        policy = session.scalar(select(InsurancePolicy).where(InsurancePolicy.policy_code == code))
        if policy is not None:
            return policy
    return session.scalar(select(InsurancePolicy).order_by(InsurancePolicy.policy_code).limit(1))


def update_case(
    session: Session,
    case: AuthorizationCase,
    values: Mapping[str, Any],
    *,
    actor: str,
) -> list[str]:
    changed = _apply_fields(case, values)
    if not changed:
        return changed
    case.updated_at = now_utc()
    session.flush()
    record_audit(
        session,
        action="desk_case_update",
        actor=actor[:64],
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
        detail="fields=" + ",".join(changed),
    )
    return changed


def _invalid(action: str, stage: str, reason: str = "") -> AppError:
    allowed = ", ".join(sorted(TRANSITIONS.get(action, frozenset()))) or "none"
    message = reason or (
        f"'{action}' is not allowed while the case is '{stage}' (allowed from: {allowed})."
    )
    return AppError("STAGE_TRANSITION_INVALID", message, 409)


def _require_text(value: Any, name: str, *, max_len: int = 2000) -> str:
    text = str(value or "").strip()
    if not text:
        raise AppError("VALIDATION_ERROR", f"{name} is required for this action.", 422)
    return text[:max_len]


def _require_amount(value: Any, name: str) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError("VALIDATION_ERROR", f"{name} must be a whole rupee amount.", 422) from exc
    if amount <= 0:
        raise AppError("VALIDATION_ERROR", f"{name} must be greater than zero.", 422)
    return amount


def apply_stage_action(
    session: Session,
    case: AuthorizationCase,
    payload: Mapping[str, Any],
    *,
    actor: str,
    now: datetime | None = None,
) -> str:
    """Apply one desk stage action. Returns the new stage."""
    current = now or now_utc()
    action = str(payload.get("action") or "")
    if action not in TRANSITIONS:
        raise AppError("VALIDATION_ERROR", f"Unknown stage action: {action or '(none)'}.", 422)
    stage = stage_of(case)
    if stage not in TRANSITIONS[action]:
        raise _invalid(action, stage)
    detail = ""

    if action == "mark_sent":
        review = review_state(session, case)
        if review.state != "acknowledged":
            raise _invalid(
                action,
                stage,
                "A senior clinician must acknowledge the checklist before the request is sent "
                f"(review state: {review.state}).",
            )
        case.sent_at = current
        case.decision_due_at = current + timedelta(hours=INSURER_DECISION_HOURS)
        case.stage = "sent"
    elif action == "record_query":
        text = _require_text(payload.get("text"), "text")
        hours = payload.get("response_due_hours")
        due_hours = QUERY_RESPONSE_DEFAULT_HOURS if hours in (None, "") else float(hours)
        if not 0 < due_hours <= 24 * 14:
            raise AppError("VALIDATION_ERROR", "response_due_hours must be 1–336.", 422)
        existing = open_queries(list_queries(session, case))
        resume = existing[0].resume_stage if (stage == "query" and existing) else stage
        if resume == "query":
            resume = "sent"
        item = CaseQuery(
            id=str(uuid4()),
            query_code=next_public_code(session, CaseQuery.query_code, "Q"),
            case_id=case.id,
            raised_at=current,
            text=text,
            response_due_at=current + timedelta(hours=due_hours),
            responded_at=None,
            response="",
            raised_by=str(payload.get("raised_by") or "Insurer/TPA")[:120],
            responded_by="",
            resume_stage=resume,
            created_at=current,
            updated_at=current,
        )
        session.add(item)
        case.stage = "query"
        detail = f"query={item.query_code}"
    elif action == "answer_query":
        query_code = _require_text(payload.get("query_id"), "query_id", max_len=32)
        response = _require_text(payload.get("response"), "response", max_len=4000)
        queries = list_queries(session, case)
        target = next((item for item in queries if item.query_code == query_code), None)
        if target is None:
            raise NotFoundError("QUERY_NOT_FOUND", "Query was not found on this case.")
        if target.responded_at is not None:
            raise _invalid(action, stage, f"Query {query_code} was already answered.")
        target.responded_at = current
        target.response = response
        target.responded_by = actor[:120]
        target.updated_at = current
        if not [item for item in open_queries(queries) if item.id != target.id]:
            resume = target.resume_stage if target.resume_stage in STAGES else "sent"
            case.stage = resume
            # Insurer clock restarts once the request is complete again.
            if resume in {"sent", "enhancement"}:
                case.decision_due_at = current + timedelta(hours=INSURER_DECISION_HOURS)
            elif resume == "discharge_sent":
                case.final_due_at = current + timedelta(hours=FINAL_APPROVAL_HOURS)
        detail = f"query={query_code}"
    elif action == "record_approval":
        amount = _require_amount(payload.get("approved_amount_inr"), "approved_amount_inr")
        case.approved_amount_inr = amount
        case.approved_at = current
        case.decision_due_at = None
        case.stage = "approved"
        detail = f"amount_inr={amount}"
    elif action == "request_enhancement":
        revised = _require_amount(payload.get("revised_estimate_inr"), "revised_estimate_inr")
        reason = _require_text(payload.get("reason"), "reason", max_len=500)
        case.revised_estimate_inr = revised
        case.enhancement_reason = reason
        case.enhancement_requested_at = current
        case.enhancement_count = int(case.enhancement_count or 0) + 1
        case.decision_due_at = current + timedelta(hours=INSURER_DECISION_HOURS)
        case.stage = "enhancement"
        detail = f"revised_inr={revised}"
    elif action == "start_discharge":
        case.stage = "discharge_pending"
    elif action == "mark_discharge_sent":
        from app.services.tpa_forms import discharge_check

        check = discharge_check(session, case)
        override = str(payload.get("override_reason") or "").strip()
        if check["status"] == "blockers" and not override:
            blockers = [item["code"] for item in check["findings"] if item["severity"] == "blocker"]
            raise AppError(
                "DISCHARGE_CHECK_BLOCKED",
                "Discharge consistency check has blockers ("
                + ", ".join(blockers)
                + "). Fix them or send with an override_reason.",
                409,
            )
        case.discharge_requested_at = current
        case.final_due_at = current + timedelta(hours=FINAL_APPROVAL_HOURS)
        case.discharge_override_reason = override[:500]
        case.stage = "discharge_sent"
        detail = f"override={int(bool(override))}"
    elif action == "close":
        case.closed_at = current
        case.stage = "closed"
    case.updated_at = current
    session.flush()
    record_audit(
        session,
        action="desk_stage_" + action,
        actor=actor[:64],
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
        detail=f"from={stage};to={case.stage};{detail}".rstrip(";"),
    )
    return str(case.stage)
