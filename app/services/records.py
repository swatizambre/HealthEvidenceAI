"""Read models for patients, policies, documents, and dashboard counts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.repository import (
    count_chunks,
    count_rows,
    get_case_by_code,
    get_document_by_code,
    get_patient_by_code,
    get_policy_by_code,
    list_cases,
    list_claims,
    list_criteria,
    list_documents_for_patient,
    list_imaging,
    list_labs,
    list_medications,
    list_notes,
    list_patients,
    list_policies,
    list_procedures,
)
from app.models import (
    AuthorizationCase,
    Claim,
    ClinicalNote,
    Document,
    DocumentFile,
    ImagingStudy,
    InsurancePolicy,
    LabResult,
    Medication,
    Patient,
    Procedure,
)
from app.schemas.api import (
    AuthorizationCaseListResponse,
    AuthorizationCaseOut,
    ClaimOut,
    CriterionOut,
    Demographics,
    DocumentListResponse,
    DocumentOut,
    EssentialsSectionOut,
    ImagingOut,
    LabOut,
    MedicationOut,
    NoteOut,
    PatientDetail,
    PatientEssentialsResponse,
    PatientListResponse,
    PatientSummary,
    PolicyDetail,
    PolicyListResponse,
    PolicySummary,
    ProcedureOut,
    StatsResponse,
    TimelineEvent,
    TimelineResponse,
    WorklistCaseOut,
    WorklistPatientOut,
    WorklistResponse,
)


def list_patient_summaries(
    session: Session,
    *,
    offset: int,
    limit: int,
    query: str | None = None,
    org_id: str | None = None,
) -> PatientListResponse:
    q = (query or "").strip().lower()
    if q:
        matched = [
            patient
            for patient in list_patients(session, offset=0, limit=500, org_id=org_id)
            if q in patient.patient_code.lower()
            or q in patient.synthetic_name.lower()
            or any(q in str(item).lower() for item in (patient.conditions or []))
        ]
        total = len(matched)
        page = matched[offset : offset + limit]
        return PatientListResponse(patients=[_summary(patient) for patient in page], total=total)
    patients = list_patients(session, offset=offset, limit=limit, org_id=org_id)
    if org_id:
        total = len(list_patients(session, offset=0, limit=10_000, org_id=org_id))
    else:
        total = count_rows(session, Patient)
    return PatientListResponse(
        patients=[_summary(patient) for patient in patients],
        total=total,
    )


def get_patient_detail(session: Session, patient_code: str) -> PatientDetail:
    from app.services.disorders import is_clinical_condition, is_clinical_procedure

    patient = require_patient(session, patient_code)
    notes = list_notes(session, patient.id)
    documents = {note.document_id: note for note in notes}
    note_documents = {
        document.id: document.document_code
        for document in list_documents_for_patient(session, patient.id)
        if document.id in documents
    }
    clinical_conditions = [
        item for item in (patient.conditions or []) if is_clinical_condition(str(item))
    ]
    clinical_procedures = [
        item for item in list_procedures(session, patient.id) if is_clinical_procedure(item.name)
    ]
    return PatientDetail(
        patient_id=patient.patient_code,
        demographics=Demographics(
            patient_id=patient.patient_code,
            synthetic_name=patient.synthetic_name,
            date_of_birth=patient.birth_date,
            sex=patient.sex,
        ),
        conditions=clinical_conditions,
        medications=[_medication(item) for item in list_medications(session, patient.id)],
        labs=[_lab(session, item) for item in list_labs(session, patient.id)],
        procedures=[_procedure(item) for item in clinical_procedures],
        imaging=[_imaging(session, item) for item in list_imaging(session, patient.id)],
        clinical_notes=[_note(item, note_documents.get(item.document_id, "")) for item in notes],
        claims=[_claim(item) for item in list_claims(session, patient.id)],
    )


def get_patient_essentials(session: Session, patient_code: str) -> PatientEssentialsResponse:
    """Chart completeness checklist for doctor/coordinator end-to-end prep.

    Decision-support only — not a diagnosis or medical device output.
    """
    from app.core.safety import DISCLAIMER
    from app.services.specialties import normalize_specialty

    detail = get_patient_detail(session, patient_code)
    note_blob = " ".join(note.content.lower() for note in detail.clinical_notes)
    allergy_hits = [
        token
        for token in ("allerg", "nkda", "adverse reaction", "hypersensitiv")
        if token in note_blob
    ]
    vital_hits = [
        token
        for token in ("blood pressure", " bp ", "heart rate", "pulse", "temperature", "spo2", " vitals")
        if token in note_blob
    ]

    sections: list[EssentialsSectionOut] = []

    def _add(
        *,
        key: str,
        label: str,
        count: int,
        highlights: list[str],
        tab: str,
        action: str,
        missing_note: str,
        thin_at: int = 1,
        unknown: bool = False,
        unknown_note: str = "",
    ) -> None:
        if unknown:
            status: Literal["present", "thin", "missing", "unknown"] = "unknown"
            note = unknown_note
        elif count == 0:
            status = "missing"
            note = missing_note
        elif count <= thin_at:
            status = "thin"
            note = "Present but thin — consider adding more for a complete packet."
        else:
            status = "present"
            note = ""
        sections.append(
            EssentialsSectionOut(
                key=key,
                label=label,
                status=status,
                count=count,
                highlights=highlights[:4],
                action=action if status in {"missing", "thin", "unknown"} else "",
                tab=tab,
                note=note,
            )
        )

    conditions = [str(item) for item in detail.conditions]
    _add(
        key="conditions",
        label="Conditions / diagnoses",
        count=len(conditions),
        highlights=conditions,
        tab="file",
        action="Document diagnosis",
        missing_note="No conditions recorded — add diagnoses on Visit note.",
        thin_at=0,
    )
    meds = [item.name for item in detail.medications]
    _add(
        key="medications",
        label="Medications",
        count=len(meds),
        highlights=meds,
        tab="meds",
        action="Document medication",
        missing_note="No medications on file — document current meds if relevant to the checklist.",
    )
    labs = [f"{item.test_name}: {item.value} {item.unit}".strip() for item in detail.labs]
    _add(
        key="labs",
        label="Labs",
        count=len(labs),
        highlights=labs,
        tab="labs",
        action="Document lab",
        missing_note="No labs attached — many PA checklists need recent results.",
    )
    notes = [item.note_type.replace("_", " ") for item in detail.clinical_notes]
    _add(
        key="notes",
        label="Clinical notes",
        count=len(detail.clinical_notes),
        highlights=notes,
        tab="notes",
        action="Add visit note",
        missing_note="No clinical notes — document the visit under the right specialty.",
    )
    imaging = [
        f"{item.modality} {item.body_part}".strip() for item in detail.imaging
    ]
    _add(
        key="imaging",
        label="Imaging",
        count=len(imaging),
        highlights=imaging,
        tab="imaging",
        action="Add imaging note",
        missing_note="No imaging studies — add a note if imaging is required for the procedure.",
        thin_at=0,
    )
    procedures = [item.name for item in detail.procedures]
    _add(
        key="procedures",
        label="Procedures",
        count=len(procedures),
        highlights=procedures,
        tab="procedures",
        action="Add visit note",
        missing_note="No procedures listed yet.",
        thin_at=0,
    )
    _add(
        key="allergies",
        label="Allergies",
        count=len(allergy_hits),
        highlights=["Mentioned in notes"] if allergy_hits else [],
        tab="notes",
        action="Add allergy note",
        missing_note="",
        unknown=not allergy_hits,
        unknown_note="Not a structured field — scan notes or document NKDA / allergies on Visit note.",
    )
    _add(
        key="vitals",
        label="Vitals",
        count=len(vital_hits),
        highlights=["Mentioned in notes"] if vital_hits else [],
        tab="notes",
        action="Add vitals in visit note",
        missing_note="",
        unknown=not vital_hits,
        unknown_note="Vitals are captured in notes when entered on Visit note.",
    )

    scored = [item for item in sections if item.key not in {"allergies", "vitals"}]
    # Only fully present sections count toward completeness (thin still needs attention).
    present_count = sum(1 for item in scored if item.status == "present")
    completeness = int(round(100 * present_count / max(len(scored), 1)))
    missing = [item.key for item in sections if item.status in {"missing", "thin"}]
    next_actions: list[str] = []
    for item in sections:
        if item.status in {"missing", "thin"} and item.action:
            next_actions.append(f"{item.action} ({item.label})")
        if len(next_actions) >= 4:
            break
    if not next_actions:
        next_actions.append("Prepare evidence packet for the planned procedure checklist.")

    specialties: list[str] = []
    for document in list_documents_for_patient(session, require_patient(session, patient_code).id):
        meta = document.document_metadata or {}
        label = str(meta.get("specialty") or meta.get("department") or "").strip()
        if label:
            specialties.append(normalize_specialty(label))
    unique_specs: list[str] = []
    seen_specs: set[str] = set()
    for specialty_name in specialties:
        if specialty_name not in seen_specs and specialty_name not in {"Laboratory", "Pharmacy"}:
            seen_specs.add(specialty_name)
            unique_specs.append(specialty_name)

    brief_bits = [
        f"{detail.demographics.synthetic_name} ({detail.patient_id})",
        f"chart ~{completeness}% structured essentials",
    ]
    if conditions:
        brief_bits.append(f"conditions: {', '.join(conditions[:3])}")
    if unique_specs:
        brief_bits.append(f"specialties: {', '.join(unique_specs[:3])}")
    if missing:
        brief_bits.append(f"needs attention: {', '.join(missing[:4])}")
    doctor_brief = " · ".join(brief_bits) + ". Decision support only — not a diagnosis."

    return PatientEssentialsResponse(
        patient_id=detail.patient_id,
        display_name=detail.demographics.synthetic_name,
        completeness_percent=completeness,
        sections=sections,
        missing_keys=missing,
        next_actions=next_actions,
        doctor_brief=doctor_brief,
        disclaimer=DISCLAIMER,
    )


def get_patient_timeline(session: Session, patient_code: str) -> TimelineResponse:
    from app.services.specialties import specialty_for_event_type

    patient = require_patient(session, patient_code)
    documents = {
        document.id: document for document in list_documents_for_patient(session, patient.id)
    }
    events: list[TimelineEvent] = []

    def _doc_context(
        document_id: str | None, event_type: str
    ) -> tuple[str, str, str | None]:
        if not document_id:
            return specialty_for_event_type(event_type), "", None
        document = documents.get(document_id)
        if document is None:
            return specialty_for_event_type(event_type), "", None
        meta = document.document_metadata or {}
        specialty = str(meta.get("specialty") or "").strip()
        if not specialty:
            specialty = specialty_for_event_type(
                event_type, department=str(meta.get("department") or "") or None
            )
        facility = str(meta.get("facility_name") or "").strip()
        return specialty, facility, document.document_code

    for note in list_notes(session, patient.id):
        specialty, facility, document_code = _doc_context(note.document_id, "clinical_note")
        events.append(
            TimelineEvent(
                event_id=note.note_code,
                event_type="clinical_note",
                timestamp=_as_utc(note.authored_at),
                source="clinical_note",
                description=f"{note.note_type}: {note.content[:160]}",
                specialty=specialty,
                facility_name=facility,
                document_id=document_code,
                title=note.note_type.replace("_", " ").title(),
            )
        )
    for lab in list_labs(session, patient.id):
        specialty, facility, document_code = _doc_context(lab.document_id, "lab_result")
        events.append(
            TimelineEvent(
                event_id=lab.lab_code,
                event_type="lab_result",
                timestamp=_as_utc(lab.collected_at),
                source="lab_result",
                description=f"{lab.test_name} result recorded: {lab.value} {lab.unit}",
                specialty=specialty,
                facility_name=facility,
                document_id=document_code,
                title=lab.test_name,
            )
        )
    for medication in list_medications(session, patient.id):
        events.append(
            TimelineEvent(
                event_id=medication.medication_code,
                event_type="medication",
                timestamp=_as_utc(medication.started_at),
                source="medication",
                description=f"{medication.name} recorded as {medication.status}",
                specialty=specialty_for_event_type("medication"),
                title=medication.name,
            )
        )
    for procedure in list_procedures(session, patient.id):
        events.append(
            TimelineEvent(
                event_id=procedure.procedure_code,
                event_type="procedure",
                timestamp=_as_utc(procedure.performed_at),
                source="procedure",
                description=procedure.name,
                specialty=specialty_for_event_type("procedure"),
                title=procedure.name,
            )
        )
    for study in list_imaging(session, patient.id):
        events.append(
            TimelineEvent(
                event_id=study.imaging_code,
                event_type="imaging_study",
                timestamp=_as_utc(study.studied_at),
                source="imaging_metadata",
                description=f"{study.modality} metadata recorded for the {study.body_part}",
                specialty=specialty_for_event_type("imaging_study"),
                title=f"{study.modality} · {study.body_part}",
            )
        )
    for claim in list_claims(session, patient.id):
        events.append(
            TimelineEvent(
                event_id=claim.claim_code,
                event_type="claim",
                timestamp=_as_utc(claim.service_date),
                source="claim",
                description=f"Synthetic claim recorded with status {claim.status}",
                specialty=specialty_for_event_type("claim"),
                title=f"Claim {claim.status}",
            )
        )
    events.sort(key=lambda event: (event.timestamp, event.event_id), reverse=True)
    return TimelineResponse(patient_id=patient.patient_code, events=events)


def list_policy_summaries(session: Session) -> PolicyListResponse:
    policies = list_policies(session)
    return PolicyListResponse(
        policies=[_policy_summary(policy) for policy in policies],
        total=len(policies),
    )


def get_policy_detail(session: Session, policy_code: str) -> PolicyDetail:
    policy = get_policy_by_code(session, policy_code)
    if policy is None:
        raise NotFoundError("POLICY_NOT_FOUND", "Policy was not found.")
    document = session.get(Document, policy.document_id)
    criteria = list_criteria(session, policy.id)
    return PolicyDetail(
        policy_id=policy.policy_code,
        title=policy.title,
        payer_name=policy.payer_name,
        procedure=policy.procedure_name,
        version=policy.version,
        content=policy.content,
        document_id="" if document is None else document.document_code,
        criteria=[
            CriterionOut(
                criterion_id=item.criterion_code,
                description=item.description,
                position=item.position,
            )
            for item in criteria
        ],
    )


def list_patient_documents(session: Session, patient_code: str) -> DocumentListResponse:
    patient = require_patient(session, patient_code)
    documents = list_documents_for_patient(session, patient.id)
    return DocumentListResponse(
        documents=[_document_out(session, document, patient.patient_code) for document in documents]
    )


def get_document_detail(session: Session, document_code: str) -> DocumentOut:
    document = get_document_by_code(session, document_code)
    if document is None:
        raise NotFoundError("DOCUMENT_NOT_FOUND", "Document was not found.")
    patient_code = None
    if document.patient_id is not None:
        patient = session.get(Patient, document.patient_id)
        patient_code = None if patient is None else patient.patient_code
    return _document_out(session, document, patient_code)


def list_authorization_cases(
    session: Session,
    *,
    org_id: str | None = None,
) -> AuthorizationCaseListResponse:
    from app.services.cycle_time import case_cycle_minutes

    return AuthorizationCaseListResponse(
        cases=[
            AuthorizationCaseOut(
                case_id=case.case_code,
                patient_id=patient_code,
                policy_id=policy_code,
                policy_title=title,
                procedure=case.procedure,
                status=_case_status(case),
                last_run_id=getattr(case, "last_run_id", None),
                lifecycle_note=str(getattr(case, "lifecycle_note", "") or ""),
                cycle_elapsed_minutes=case_cycle_minutes(case),
            )
            for case, patient_code, policy_code, title in list_cases(session, org_id=org_id)
        ]
    )


def system_stats(session: Session, *, org_id: str | None = None) -> StatsResponse:
    if not org_id:
        return StatsResponse(
            patients=count_rows(session, Patient),
            authorization_cases=count_rows(session, AuthorizationCase),
            policies=count_rows(session, InsurancePolicy),
            system_status="ok",
        )
    patients = int(
        session.scalar(select(func.count()).select_from(Patient).where(Patient.org_id == org_id))
        or 0
    )
    cases = len(list_cases(session, org_id=org_id))
    return StatsResponse(
        patients=patients,
        authorization_cases=cases,
        policies=count_rows(session, InsurancePolicy),
        system_status="ok",
    )


def clinician_worklist(
    session: Session,
    *,
    patient_limit: int = 6,
    case_limit: int = 6,
    org_id: str | None = None,
    assignee_subject: str | None = None,
) -> WorklistResponse:
    """Doctor Today queue: actionable reviews first, then recent charts."""
    from app.services.specialties import normalize_specialty, specialty_for_event_type
    subject = (assignee_subject or "").strip()

    patient_query = select(Patient).order_by(Patient.updated_at.desc())
    if org_id:
        patient_query = patient_query.where(Patient.org_id == org_id)
    patients = list(
        session.scalars(patient_query.limit(max(patient_limit, 1))).all()
    )
    recent_patients = []
    for patient in patients:
        specialties: list[str] = []
        for document in list_documents_for_patient(session, patient.id):
            meta = document.document_metadata or {}
            label = str(meta.get("specialty") or meta.get("department") or "").strip()
            if label:
                specialties.append(normalize_specialty(label))
            elif document.document_type == "lab_result":
                specialties.append(specialty_for_event_type("lab_result"))
            elif document.document_type == "clinical_note":
                specialties.append(specialty_for_event_type("clinical_note"))
        seen: set[str] = set()
        unique = []
        for item in specialties:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        # Prefer clinical specialties over always-present Lab/Pharmacy noise in the summary.
        preferred = [
            item
            for item in unique
            if item not in {"Laboratory", "Pharmacy"}
        ] or unique
        recent_patients.append(
            WorklistPatientOut(
                patient_id=patient.patient_code,
                display_name=patient.synthetic_name,
                sex=patient.sex,
                condition_summary=_condition_summary(patient.conditions),
                specialties=preferred[:3],
            )
        )

    cases = list_cases(session, org_id=org_id)
    open_rows = [row for row in cases if _case_status(row[0]) != "closed_as_draft"]

    def _case_sort_key(row: tuple[AuthorizationCase, str, str, str]) -> tuple[int, int, str]:
        case, _patient_code, _policy_code, title = row
        status = _case_status(case)
        status_rank = {
            "needs_documentation": 0,
            "ready_for_human": 1,
            "queued": 2,
        }.get(status, 3)
        catalogish = _is_catalog_filler(case.procedure, title)
        # Actionable / OPD / demo first; catalog seed filler last.
        return (status_rank, 1 if catalogish else 0, case.case_code)

    ranked = sorted(open_rows, key=_case_sort_key)
    # Prefer non-catalog when there are enough; otherwise fill from ranked list.
    preferred_cases = [row for row in ranked if not _is_catalog_filler(row[0].procedure, row[3])]
    selected = (preferred_cases or ranked)[:case_limit]
    if len(selected) < case_limit:
        for row in ranked:
            if row in selected:
                continue
            selected.append(row)
            if len(selected) >= case_limit:
                break

    from app.services.cycle_time import case_cycle_minutes
    from app.services.disorders import is_clinical_procedure

    open_cases = []
    for case, patient_code, policy_code, title in selected:
        status = _case_status(case)
        note = str(getattr(case, "lifecycle_note", "") or "")
        gap_focus, specialty_hint = _gap_coaching(note)
        raw_procedure = str(case.procedure or "").strip()
        title_clean = (title or "").strip()
        if raw_procedure and is_clinical_procedure(raw_procedure) and "catalog" not in raw_procedure.lower():
            procedure_label = raw_procedure
        elif title_clean and "catalog" not in title_clean.lower() and "dynamic" not in title_clean.lower():
            procedure_label = title_clean
        else:
            procedure_label = "Evidence packet"
        assignee = str(getattr(case, "assigned_to", None) or "").strip() or None
        # Prefer professional policy labels at read-time (A6).
        policy_title = (
            title_clean
            if title_clean
            and "catalog" not in title_clean.lower()
            and "dynamic" not in title_clean.lower()
            else "Prior authorization evidence checklist"
        )
        if procedure_label == "Evidence packet":
            procedure_label = "Evidence pack"
        from app.core.config import get_settings

        cycle_mins = case_cycle_minutes(case)
        sla = max(15, int(get_settings().packet_sla_minutes or 240))
        open_cases.append(
            WorklistCaseOut(
                case_id=case.case_code,
                patient_id=patient_code,
                procedure=procedure_label,
                policy_title=policy_title,
                policy_id=policy_code,
                status=status,
                next_hint=_case_next_hint(status),
                gap_label=note[:200] if status == "needs_documentation" and note else "",
                gap_focus=gap_focus if status == "needs_documentation" else "",
                specialty_hint=specialty_hint if status == "needs_documentation" else "",
                cycle_elapsed_minutes=cycle_mins,
                sla_minutes=sla,
                sla_breached=bool(cycle_mins is not None and cycle_mins >= sla),
                assigned_to=assignee,
                assigned_to_me=bool(subject and assignee and assignee == subject),
            )
        )
    my_cases = [row for row in open_cases if row.assigned_to_me]
    unassigned = [row for row in open_cases if not row.assigned_to]
    return WorklistResponse(
        recent_patients=recent_patients,
        open_cases=open_cases,
        my_cases=my_cases,
        unassigned_cases=unassigned,
        assignment_enabled=True,
    )


def _case_next_hint(status: str) -> str:
    """Staff coaching from AMA-style PA workflows — organize work, never decide coverage."""
    return {
        "needs_documentation": "Close chart gaps with a Visit note, then re-check readiness",
        "ready_for_human": "Check citations in Reviews, then confirm or send back for notes",
        "queued": "Prepare evidence packet before procedure review",
        "closed_as_draft": "Packet closed as draft — reopen only if documentation changed",
    }.get(status, "Prepare evidence packet before procedure review")


def _gap_coaching(note: str) -> tuple[str, str]:
    """Map lifecycle gap text to Encounter focus + specialty for coordinator handoff."""
    lower = note.lower()
    if any(token in lower for token in ("lab", "a1c", "laboratory", "hemoglobin")):
        return "labs", "Laboratory"
    if any(token in lower for token in ("medic", "drug", "therapy")):
        return "meds", "Pharmacy"
    if any(token in lower for token in ("imaging", "mri", "ct ", "x-ray")):
        return "note", "Radiology"
    if any(token in lower for token in ("diagnos", "condition")):
        return "diagnoses", "General medicine"
    if note.strip():
        return "note", "General medicine"
    return "", ""


def _is_catalog_filler(procedure: str, policy_title: str) -> bool:
    procedure_l = procedure.lower()
    title_l = policy_title.lower()
    return procedure_l.startswith("catalog procedure") or title_l.startswith("catalog payer")


def update_case_lifecycle(
    session: Session,
    *,
    case_code: str | None,
    status: str,
    run_id: str | None = None,
    note: str = "",
) -> None:
    """Persist decision-support case status after a review or clinician action."""
    if not case_code:
        return
    case = get_case_by_code(session, case_code)
    if case is None:
        return
    from app.services.cycle_time import stamp_prep_started, stamp_review_ready

    case.status = status
    if run_id:
        case.last_run_id = run_id
    if note:
        case.lifecycle_note = note[:500]
    if status in {"needs_documentation", "queued"}:
        stamp_prep_started(case)
    if status == "ready_for_human":
        stamp_prep_started(case)
        stamp_review_ready(case)
    session.add(case)
    session.flush()


def _case_status(case: AuthorizationCase) -> Literal[
    "queued", "needs_documentation", "ready_for_human", "closed_as_draft"
]:
    value = str(getattr(case, "status", None) or "queued")
    if value == "needs_documentation":
        return "needs_documentation"
    if value == "ready_for_human":
        return "ready_for_human"
    if value == "closed_as_draft":
        return "closed_as_draft"
    return "queued"


def _condition_summary(conditions: list[str] | None, *, limit: int = 2) -> str:
    from app.services.disorders import is_clinical_condition

    clinical = [item for item in (conditions or []) if item and is_clinical_condition(str(item))]
    items = [_display_condition(item) for item in clinical]
    items = [item for item in items if item]
    if not items:
        return "No clinical conditions recorded"
    head = "; ".join(items[:limit])
    extra = len(items) - limit
    return f"{head}; +{extra} more" if extra > 0 else head


def _display_condition(value: str) -> str:
    """Strip ontology suffixes like (disorder) for clinician-facing summaries."""
    import re

    cleaned = re.sub(
        r"\s*\((?:disorder|situation|finding|procedure|body structure|morphologic abnormality|"
        r"observable entity|qualifier value|organism|substance)\)\s*$",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    return cleaned.strip() or value.strip()


def require_patient(session: Session, patient_code: str) -> Patient:
    patient = get_patient_by_code(session, patient_code)
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "Patient was not found.")
    return patient


def _summary(patient: Patient) -> PatientSummary:
    from app.services.disorders import clinical_conditions

    return PatientSummary(
        patient_id=patient.patient_code,
        synthetic_name=patient.synthetic_name,
        date_of_birth=patient.birth_date,
        sex=patient.sex,
        # Synthea social findings ("Received higher education", "Stress", …) are not
        # clinical conditions — never list them as such.
        conditions=clinical_conditions(patient.conditions),
    )


def _medication(item: Medication) -> MedicationOut:
    return MedicationOut(
        medication_id=item.medication_code,
        name=item.name,
        dose=item.dose,
        status=item.status,
        started_at=_as_utc(item.started_at),
    )


def _lab(session: Session, item: LabResult) -> LabOut:
    document = session.get(Document, item.document_id) if item.document_id else None
    document_code = document.document_code if document else None
    has_file = False
    if document is not None:
        has_file = (
            session.scalar(select(DocumentFile.id).where(DocumentFile.document_id == document.id))
            is not None
        )
    return LabOut(
        lab_id=item.lab_code,
        test_name=item.test_name,
        value=item.value,
        unit=item.unit,
        collected_at=_as_utc(item.collected_at),
        document_id=document_code,
        has_file=has_file,
    )


def _procedure(item: Procedure) -> ProcedureOut:
    return ProcedureOut(
        procedure_id=item.procedure_code,
        name=item.name,
        performed_at=_as_utc(item.performed_at),
    )


def _imaging(session: Session, item: ImagingStudy) -> ImagingOut:
    document = session.get(Document, item.document_id) if item.document_id else None
    document_code = document.document_code if document else None
    has_file = False
    if document is not None:
        has_file = (
            session.scalar(select(DocumentFile.id).where(DocumentFile.document_id == document.id))
            is not None
        )
    return ImagingOut(
        imaging_id=item.imaging_code,
        modality=item.modality,
        body_part=item.body_part,
        study_date=_as_utc(item.studied_at),
        description=item.description,
        document_id=document_code,
        has_file=has_file,
    )


def _note(item: ClinicalNote, document_code: str) -> NoteOut:
    return NoteOut(
        note_id=item.note_code,
        note_type=item.note_type,
        content=item.content,
        authored_at=_as_utc(item.authored_at),
        document_id=document_code,
    )


def _claim(item: Claim) -> ClaimOut:
    return ClaimOut(
        claim_id=item.claim_code,
        status=item.status,
        amount_cents=item.amount_cents,
        service_date=_as_utc(item.service_date),
    )


def _policy_summary(policy: InsurancePolicy) -> PolicySummary:
    return PolicySummary(
        policy_id=policy.policy_code,
        title=policy.title,
        payer_name=policy.payer_name,
        procedure=policy.procedure_name,
    )


def _document_out(session: Session, document: Document, patient_code: str | None) -> DocumentOut:
    metadata = {
        str(key): value
        for key, value in document.document_metadata.items()
        if isinstance(value, str | int | float | bool)
    }
    file_row = session.scalar(
        select(DocumentFile).where(DocumentFile.document_id == document.id)
    )
    has_file = file_row is not None
    return DocumentOut(
        document_id=document.document_code,
        patient_id=patient_code,
        document_type=document.document_type,
        source=document.source,
        created_at=_as_utc(document.created_at),
        content=document.content,
        metadata=metadata,
        chunk_count=count_chunks(session, document.id),
        has_file=has_file,
        original_filename=(
            file_row.original_filename
            if file_row
            else str(metadata.get("original_filename") or "")
        ),
        content_type=(
            file_row.content_type if file_row else str(metadata.get("content_type") or "")
        ),
        file_url=(
            f"/api/v1/documents/{document.document_code}/file" if has_file else None
        ),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
