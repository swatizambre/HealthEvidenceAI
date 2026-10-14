"""Case checklist + the ONE readiness computation used across the product.

Every readiness number shown for a case — TPA desk worklist, case workspace,
evidence-pack prepare, Reviews scorecard — comes from :func:`summarize_readiness`
over the checklist built here, so the numbers never disagree:

    readiness_percent = supported / required   (required checklist items only)

Checklist groups:
- ``form``      — cashless request fields recorded on the case (desk cases only)
- ``clinical``  — policy criteria scored by the evaluator / latest review run
- ``documents`` — supporting-document criteria (``rule.group == "documents"``)

Documentation readiness only — never an approval or coverage decision.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuthorizationCase, Document, InsurancePolicy, Patient, PolicyCriterion

STATUS_SUPPORTED = "SUPPORTED"
STATUS_MISSING = "MISSING"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_NOT_SUPPORTED = "NOT_SUPPORTED"
_STATUSES = frozenset({STATUS_SUPPORTED, STATUS_MISSING, STATUS_UNKNOWN, STATUS_NOT_SUPPORTED})

GROUP_FORM = "form"
GROUP_CLINICAL = "clinical"
GROUP_DOCUMENTS = "documents"
_GROUPS = frozenset({GROUP_FORM, GROUP_CLINICAL, GROUP_DOCUMENTS})

EXCERPT_MAX = 280


@dataclass(frozen=True)
class Citation:
    document_id: str
    chunk_id: str
    source: str
    excerpt: str
    date: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "source": self.source,
            "excerpt": self.excerpt,
            "date": self.date,
        }


@dataclass
class ChecklistItem:
    item_id: str
    group: str
    label: str
    status: str
    required: bool = True
    reason: str = ""
    fix_hint: str = ""
    citations: list[Citation] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "group": self.group,
            "label": self.label,
            "status": self.status,
            "required": self.required,
            "reason": self.reason,
            "fix_hint": self.fix_hint,
            "citations": [item.as_dict() for item in self.citations],
        }


@dataclass(frozen=True)
class ReadinessSummary:
    percent: int
    required: int
    supported: int
    missing: int
    unknown: int
    not_supported: int
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "percent": self.percent,
            "required": self.required,
            "supported": self.supported,
            "missing": self.missing,
            "unknown": self.unknown,
            "not_supported": self.not_supported,
            "label": self.label,
        }

    @property
    def open_items(self) -> int:
        return self.required - self.supported


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def summarize_readiness(items: Iterable[ChecklistItem]) -> ReadinessSummary:
    """THE readiness computation: supported / required over the case checklist."""
    required = [item for item in items if item.required]
    supported = sum(1 for item in required if item.status == STATUS_SUPPORTED)
    missing = sum(1 for item in required if item.status == STATUS_MISSING)
    unknown = sum(1 for item in required if item.status == STATUS_UNKNOWN)
    not_supported = sum(1 for item in required if item.status == STATUS_NOT_SUPPORTED)
    total = len(required)
    percent = int(round(100 * supported / total)) if total else 0
    if total == 0:
        label = "No checklist items yet"
    elif supported == total:
        label = "All required items supported"
    else:
        parts: list[str] = []
        if missing:
            parts.append(f"{_plural(missing, 'item')} missing")
        if unknown:
            parts.append(f"{unknown} unclear")
        if not_supported:
            parts.append(f"{not_supported} not supported")
        label = " · ".join(parts) or f"{_plural(total - supported, 'item')} open"
    return ReadinessSummary(
        percent=percent,
        required=total,
        supported=supported,
        missing=missing,
        unknown=unknown,
        not_supported=not_supported,
        label=label,
    )


# --------------------------------------------------------------------------- results


def _field(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def normalize_results(results: Iterable[Any]) -> list[dict[str, Any]]:
    """Accept review-state dicts, CriterionResult models or evaluator Evaluations."""
    normalized: list[dict[str, Any]] = []
    for entry in results or []:
        status = str(_field(entry, "status", "") or "").upper()
        if status not in _STATUSES:
            status = STATUS_UNKNOWN
        evidence = []
        for ref in _field(entry, "evidence", None) or []:
            evidence.append(
                {
                    "document_id": str(_field(ref, "document_id", "") or ""),
                    "chunk_id": str(_field(ref, "chunk_id", "") or ""),
                    "source": str(_field(ref, "source", "") or "evidence"),
                    "text_reference": str(
                        _field(ref, "text_reference", "") or _field(ref, "content", "") or ""
                    ),
                }
            )
        normalized.append(
            {
                "criterion_id": str(_field(entry, "criterion_id", "") or ""),
                "criterion": str(_field(entry, "criterion", "") or ""),
                "status": status,
                "reason": str(_field(entry, "reason", "") or ""),
                "evidence": evidence,
            }
        )
    return normalized


def clinical_results(results: Iterable[Any]) -> list[dict[str, Any]]:
    """Drop Synthea social/admin noise rows (same filter packet prepare always used)."""
    from app.services.disorders import is_clinical_criterion_text

    rows = normalize_results(results)
    kept = [row for row in rows if is_clinical_criterion_text(row["criterion"])]
    # Fall back to the full list if filtering would empty a seeded policy mid-demo.
    return kept or rows


def readiness_from_results(results: Iterable[Any]) -> ReadinessSummary:
    """Readiness when there is no case row (criteria only, every item required)."""
    return summarize_readiness(_criterion_items(clinical_results(results), {}, {}))


# --------------------------------------------------------------------------- checklist


def is_desk_case(case: AuthorizationCase) -> bool:
    return bool(str(getattr(case, "payer_type", "") or "").strip())


def form_items(case: AuthorizationCase) -> list[ChecklistItem]:
    """Cashless request fields the desk must fill before sending (desk cases only)."""
    if not is_desk_case(case):
        return []
    payer_type = str(case.payer_type or "")
    insurer = str(case.insurer_name or "").strip()
    tpa = str(case.tpa_name or "").strip()
    items: list[ChecklistItem] = []

    def add(item_id: str, label: str, ok: bool, hint: str, reason_missing: str) -> None:
        items.append(
            ChecklistItem(
                item_id=f"form:{item_id}",
                group=GROUP_FORM,
                label=label,
                status=STATUS_SUPPORTED if ok else STATUS_MISSING,
                required=True,
                reason="Recorded on the case." if ok else reason_missing,
                fix_hint="" if ok else hint,
            )
        )

    payer_ok = bool(insurer) and (payer_type != "tpa" or bool(tpa))
    add(
        "payer",
        "Insurer / TPA identified",
        payer_ok,
        "Enter the insurer name (and TPA if the policy is serviced by one).",
        "Insurer or TPA name is not recorded.",
    )
    if payer_type != "self_pay":
        add(
            "policy_number",
            "Policy / member ID number",
            bool(str(case.policy_number or "").strip()),
            "Copy the policy or e-card number from the patient's health card.",
            "Policy number is not recorded.",
        )
    diagnosis = str(case.provisional_diagnosis or "").strip()
    icd = str(case.icd10_code or "").strip()
    add(
        "diagnosis_icd10",
        "Provisional diagnosis with ICD-10",
        bool(diagnosis and icd),
        "Record the provisional diagnosis and its ICD-10 code from the admission note.",
        "Provisional diagnosis is not recorded."
        if not diagnosis
        else "ICD-10 code for the provisional diagnosis is not recorded.",
    )
    add(
        "treatment",
        "Proposed line of treatment / procedure",
        bool(str(case.proposed_treatment or "").strip()),
        "Record the planned procedure or line of treatment.",
        "Proposed treatment is not recorded.",
    )
    add(
        "treating_doctor",
        "Treating doctor named",
        bool(str(case.treating_doctor or "").strip()),
        "Record the treating doctor's name and registration.",
        "Treating doctor is not recorded.",
    )
    add(
        "admission",
        "Admission date/time and type",
        case.admitted_at is not None and bool(str(case.admission_type or "").strip()),
        "Record the admission (or planned admission) date and time.",
        "Admission date/time is not recorded.",
    )
    add(
        "cost_estimate",
        "Cost estimate (₹)",
        bool(case.estimated_cost_inr and case.estimated_cost_inr > 0),
        "Enter the estimated cost from the billing desk.",
        "Estimated cost is not recorded.",
    )
    return items


def _fix_hint(group: str, status: str, missing_label: str) -> str:
    if status == STATUS_SUPPORTED:
        return ""
    if status == STATUS_UNKNOWN:
        return "Notes disagree or are unclear — ask the treating doctor to clarify in a visit note."
    if status == STATUS_NOT_SUPPORTED:
        return "The chart states the opposite — confirm with the treating doctor before sending."
    if group == GROUP_DOCUMENTS:
        return f"Attach or upload: {missing_label}."
    return f"Document in the chart: {missing_label}."


def _criterion_items(
    results: list[dict[str, Any]],
    rules: Mapping[str, Mapping[str, Any]],
    doc_dates: Mapping[str, str],
) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for row in results:
        rule = rules.get(row["criterion_id"]) or {}
        group = str(rule.get("group") or GROUP_CLINICAL)
        if group not in _GROUPS or group == GROUP_FORM:
            group = GROUP_CLINICAL
        required = bool(rule.get("required", True))
        missing_label = str(rule.get("missing_label") or row["criterion"])
        citations = [
            Citation(
                document_id=ref["document_id"],
                chunk_id=ref["chunk_id"],
                source=ref["source"],
                excerpt=ref["text_reference"][:EXCERPT_MAX],
                date=doc_dates.get(ref["document_id"]),
            )
            for ref in row["evidence"]
            if ref["document_id"] and ref["chunk_id"]
        ]
        items.append(
            ChecklistItem(
                item_id=row["criterion_id"] or f"crit-{len(items) + 1}",
                group=group,
                label=str(rule.get("label") or row["criterion"]),
                status=row["status"],
                required=required,
                reason=row["reason"],
                fix_hint=_fix_hint(group, row["status"], missing_label),
                citations=citations,
            )
        )
    return items


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _latest_run_results(session: Session, case: AuthorizationCase) -> list[Any] | None:
    run_id = str(getattr(case, "last_run_id", "") or "").strip()
    if not run_id:
        return None
    from app.agents.runs import load_run

    state = load_run(run_id, session)
    if not state:
        return None
    results = state.get("criterion_results")
    if isinstance(results, list) and results:
        return results
    return None


def live_rule_results(session: Session, patient: Patient, policy: InsurancePolicy) -> list[Any]:
    """Deterministic rule scoring over the chart (no LLM) — used before any review run."""
    from app.db.repository import list_criteria
    from app.services.context import load_patient_records
    from app.services.evaluator import CriterionInput, evaluate_criteria
    from app.services.safety_net import apply_safety_net

    criteria = [
        CriterionInput(code=row.criterion_code, description=row.description, rule=dict(row.rule or {}))
        for row in list_criteria(session, policy.id)
    ]
    records = load_patient_records(session, patient)
    return list(apply_safety_net(evaluate_criteria(criteria, records.notes, records.labs)))


def _document_presence(
    item: ChecklistItem,
    rule: Mapping[str, Any],
    documents: Sequence[Document],
    session: Session,
) -> None:
    """Upgrade a documents-group item when a document of the named type is on file."""
    wanted = [str(value).lower() for value in rule.get("document_types") or [] if value]
    if item.status == STATUS_SUPPORTED or not wanted:
        return
    for document in documents:
        doc_type = str(document.document_type or "").lower()
        if not any(token in doc_type for token in wanted):
            continue
        from app.db.repository import chunks_by_document

        chunks = chunks_by_document(session, [document.id]).get(document.id) or []
        if not chunks:
            continue
        item.status = STATUS_SUPPORTED
        item.reason = "A document of the required type is on file."
        item.fix_hint = ""
        item.citations = [
            Citation(
                document_id=document.document_code,
                chunk_id=chunks[0].chunk_code,
                source=document.document_type,
                excerpt=chunks[0].content.strip()[:EXCERPT_MAX],
                date=_iso(document.created_at),
            )
        ]
        return


def build_case_checklist(
    session: Session,
    case: AuthorizationCase,
    *,
    criterion_results: Iterable[Any] | None = None,
) -> list[ChecklistItem]:
    """Form items + clinical/document criteria for one case.

    ``criterion_results`` (e.g. a just-finished review) wins; otherwise the case's
    latest review run is used; otherwise the deterministic rules are run live.
    """
    patient = session.get(Patient, case.patient_id)
    policy = session.get(InsurancePolicy, case.policy_id)
    items = form_items(case)
    if patient is None or policy is None:
        return items

    if criterion_results is not None:
        raw: list[Any] | None = list(criterion_results)
    else:
        raw = _latest_run_results(session, case)
    if raw is None:
        raw = live_rule_results(session, patient, policy)
    results = clinical_results(raw)

    rules: dict[str, dict[str, Any]] = {
        row.criterion_code: dict(row.rule or {})
        for row in session.scalars(
            select(PolicyCriterion).where(PolicyCriterion.policy_id == policy.id)
        ).all()
    }
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.patient_id == patient.id)
            .order_by(Document.created_at.desc(), Document.document_code)
        ).all()
    )
    doc_dates = {doc.document_code: _iso(doc.created_at) or "" for doc in documents}
    criterion_items = _criterion_items(results, rules, doc_dates)
    for item in criterion_items:
        if item.group == GROUP_DOCUMENTS:
            _document_presence(item, rules.get(item.item_id) or {}, documents, session)
    return items + criterion_items


def readiness_for_case(
    session: Session,
    case: AuthorizationCase,
    *,
    criterion_results: Iterable[Any] | None = None,
) -> ReadinessSummary:
    return summarize_readiness(
        build_case_checklist(session, case, criterion_results=criterion_results)
    )


def readiness_for_case_code(
    session: Session | None,
    case_code: str | None,
    criterion_results: Iterable[Any],
) -> ReadinessSummary:
    """Readiness for a review state: case checklist when the case exists, else criteria only."""
    results = list(criterion_results)
    if session is not None and case_code:
        from app.db.repository import get_case_by_code

        case = get_case_by_code(session, case_code)
        if case is not None:
            return readiness_for_case(session, case, criterion_results=results)
    return readiness_from_results(results)
