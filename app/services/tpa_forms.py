"""Pre-auth request form (IRDAI hospital section, illustrative) and discharge consistency check.

The field list is an illustrative mapping of the IRDAI standard cashless request form
(hospital section). Values are pre-filled from the case, patient demographics and the
chart; every field says where its value came from. Not a submission to any insurer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.repository import (
    chunks_by_document,
    list_imaging,
    list_labs,
    list_notes,
    list_procedures,
)
from app.models import AuthorizationCase, ClinicalNote, Document, InsurancePolicy, Patient
from app.services.case_checklist import EXCERPT_MAX, GROUP_DOCUMENTS, build_case_checklist
from app.services.tpa_desk import age_years, aware, format_inr, iso

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
FORM_VERSION = "IRDAI cashless request (hospital section) — illustrative field set"

_SURGICAL = re.compile(
    r"ectomy|plasty|otomy|ostomy|replacement|arthroplasty|lscs|caesarean|cesarean|"
    r"c-section|phaco|iol|angioplasty|ptca|stent|orif|fixation|surgery|surgical|"
    r"laparoscopic|repair|excision|implant",
    re.I,
)
_MATERNITY = re.compile(r"lscs|caesarean|cesarean|c-section|delivery|pregnan|maternity|obstetric", re.I)
_INJURY = re.compile(r"\brta\b|road traffic|accident|injury|trauma|fracture|assault|fall\b|mlc", re.I)
_IMPLANT = re.compile(
    r"implant|\biol\b|lens|replacement|arthroplasty|stent|ptca|angioplasty|orif|plate|nail", re.I
)
_ICD = re.compile(r"\b([A-TV-Z][0-9][0-9AB](?:\.[0-9A-Z]{1,4})?)\b")
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*)", re.I)

# Chronic illness -> chart needles (past-history section).
_CHRONIC: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("history_diabetes", "Diabetes", ("diabetes", "diabetic", "type 2 dm", "t2dm")),
    ("history_hypertension", "Hypertension", ("hypertension", "hypertensive")),
    ("history_heart_disease", "Heart disease", ("coronary", "ischemic heart", "ischaemic heart",
                                                 "heart failure", "myocardial infarction")),
    ("history_asthma_copd", "Asthma / COPD / bronchitis", ("asthma", "copd", "chronic obstructive")),
    ("history_kidney", "Kidney disease", ("chronic kidney", "ckd", "renal failure")),
    ("history_cancer", "Cancer", ("cancer", "carcinoma", "malignan")),
    ("history_thyroid", "Thyroid disorder", ("hypothyroid", "hyperthyroid", "thyroid")),
)


def _field(
    key: str,
    label: str,
    value: Any,
    source: str,
    *,
    required: bool,
) -> dict[str, Any]:
    text = "" if value is None else str(value).strip()
    return {
        "key": key,
        "label": label,
        "value": text or None,
        "source": source if text else "missing",
        "required": required,
    }


def _case_value(key: str, label: str, value: Any, *, required: bool) -> dict[str, Any]:
    return _field(key, label, value, "case", required=required)


def _note_texts(session: Session, patient: Patient) -> list[ClinicalNote]:
    return list_notes(session, patient.id)


def _duration_near(text: str, needle: str) -> str:
    lower = text.lower()
    index = lower.find(needle)
    if index < 0:
        return ""
    window = lower[index : index + 120].split("\n")[0]
    match = re.search(r"(?:for|since|x)\s*(\d+\s*(?:years?|yrs?|months?|weeks?|days?)|\d{4})", window)
    return match.group(1) if match else ""


def _chronic_history(session: Session, patient: Patient) -> list[dict[str, Any]]:
    from app.services.disorders import is_clinical_condition
    from app.services.evaluator import find_affirmed_phrase

    conditions = [str(item) for item in (patient.conditions or []) if is_clinical_condition(str(item))]
    notes = _note_texts(session, patient)
    fields: list[dict[str, Any]] = []
    for key, label, needles in _CHRONIC:
        found_value = ""
        for condition in conditions:
            lower = condition.lower()
            if any(needle in lower for needle in needles):
                found_value = re.sub(r"\s*\((?:disorder|finding)\)\s*$", "", condition, flags=re.I)
                break
        duration = ""
        for note in notes:
            phrase = find_affirmed_phrase(note.content or "", list(needles))
            if phrase:
                duration = duration or _duration_near(note.content or "", phrase)
                found_value = found_value or phrase.capitalize()
        if found_value:
            value = f"Yes — {found_value}" + (f" ({duration})" if duration else "")
            fields.append(_field(key, label, value, "chart", required=False))
        else:
            fields.append(
                {"key": key, "label": label, "value": "Not documented", "source": "chart",
                 "required": False}
            )
    return fields


def _investigations(session: Session, patient: Patient) -> str:
    labs = list_labs(session, patient.id)
    imaging = list_imaging(session, patient.id)
    parts: list[str] = []
    for lab in sorted(labs, key=lambda item: aware(item.collected_at) or _EPOCH, reverse=True)[:6]:
        parts.append(f"{lab.test_name}: {lab.value} {lab.unit}".strip())
    for study in imaging[-3:]:
        parts.append(f"{study.modality} {study.body_part}: {study.description}"[:160])
    return "; ".join(parts)


def _presenting_complaints(session: Session, patient: Patient) -> str:
    for note in reversed(_note_texts(session, patient)):
        for line in (note.content or "").splitlines():
            if re.match(r"\s*(presenting complaints?|chief complaints?|c/o)\s*[:\-]", line, re.I):
                return line.split(":", 1)[-1].strip()[:300]
    return ""


def preauth_form(session: Session, case: AuthorizationCase) -> dict[str, Any]:
    patient = session.get(Patient, case.patient_id)
    policy = session.get(InsurancePolicy, case.policy_id)
    extra = dict(case.form_extra or {})
    costs = dict(case.cost_breakdown_inr or {})
    treatment = str(case.proposed_treatment or case.procedure or "")
    context = " ".join([treatment, str(case.provisional_diagnosis or ""), policy.title if policy else ""])
    surgical = bool(_SURGICAL.search(context))
    maternity = bool(_MATERNITY.search(context))
    injury = bool(_INJURY.search(context))
    tpa_required = str(case.payer_type or "") == "tpa"

    def extra_field(key: str, label: str, *, required: bool, fallback: Any = None,
                    fallback_source: str = "chart") -> dict[str, Any]:
        if extra.get(key) not in (None, ""):
            return _case_value(key, label, extra.get(key), required=required)
        return _field(key, label, fallback, fallback_source, required=required)

    patient_fields = [
        _field("patient_name", "Name of the patient", patient.synthetic_name if patient else None,
               "chart", required=True),
        _field("patient_id", "Hospital patient ID / MRN", patient.patient_code if patient else None,
               "chart", required=True),
        _field("age", "Age (years)", age_years(patient.birth_date) if patient else None, "chart",
               required=True),
        _field("sex", "Gender", patient.sex if patient else None, "chart", required=True),
        _field("date_of_birth", "Date of birth",
               patient.birth_date.isoformat() if patient and patient.birth_date else None,
               "chart", required=False),
        _case_value("payer_type", "Payer type", case.payer_type, required=True),
        _case_value("insurer_name", "Insurance company", case.insurer_name, required=True),
        _case_value("tpa_name", "TPA name", case.tpa_name, required=tpa_required),
        _case_value("policy_number", "Policy number / member ID", case.policy_number,
                    required=str(case.payer_type or "") != "self_pay"),
    ]

    complaints = _presenting_complaints(session, patient) if patient else ""
    doctor_fields = [
        _case_value("treating_doctor", "Name of the treating doctor", case.treating_doctor,
                    required=True),
        extra_field("nature_of_illness", "Nature of illness / presenting complaints",
                    required=True, fallback=complaints),
        extra_field("illness_duration", "Duration of present ailment", required=False),
        _case_value("provisional_diagnosis", "Provisional diagnosis", case.provisional_diagnosis,
                    required=True),
        _case_value("icd10_code", "ICD-10 code (diagnosis)", case.icd10_code, required=True),
        _case_value("proposed_treatment", "Proposed line of treatment", treatment, required=True),
        extra_field("investigations", "Investigations / medical management details",
                    required=True, fallback=_investigations(session, patient) if patient else ""),
        extra_field("route_of_drug_administration", "Route of drug administration",
                    required=not surgical),
    ]
    if surgical:
        doctor_fields.append(_case_value("surgery_name", "Name of surgery", treatment, required=True))
        doctor_fields.append(
            extra_field("surgery_icd10_pcs", "ICD-10 PCS code (surgery)", required=False)
        )
    if injury:
        doctor_fields.extend(
            [
                extra_field("injury_date", "Date of injury / accident", required=True),
                extra_field("injury_cause", "How did the injury occur", required=True),
                extra_field("mlc_number", "Medico-legal case (MLC) number", required=True),
                extra_field("police_report", "Reported to police / FIR number", required=True),
                extra_field("alcohol_involved", "Injury under influence of alcohol/drugs",
                            required=False),
            ]
        )
    if maternity:
        doctor_fields.extend(
            [
                extra_field("gpla", "Maternity: G / P / L / A", required=True),
                extra_field("expected_delivery_date", "Expected date of delivery", required=True),
            ]
        )

    expected_days: Any = extra.get("expected_days")
    admitted = aware(case.admitted_at)
    expected_out = aware(case.expected_discharge_at)
    expected_source = "case"
    if expected_days in (None, "") and admitted and expected_out:
        expected_days = max(1, round((expected_out - admitted).total_seconds() / 86400))
    admission_fields = [
        _case_value("admitted_at", "Date and time of admission", iso(case.admitted_at),
                    required=True),
        _case_value("admission_type", "Emergency / planned", case.admission_type, required=True),
        _field("expected_days", "Expected length of stay (days)", expected_days, expected_source,
               required=True),
        extra_field("room_type", "Room type", required=True),
    ]

    history_fields = _chronic_history(session, patient) if patient else []

    def cost(key: str, label: str) -> dict[str, Any]:
        raw = costs.get(key)
        return _case_value(
            f"cost_{key}", label, f"₹{format_inr(int(raw))}" if raw not in (None, "") else None,
            required=False,
        )

    total = case.estimated_cost_inr
    cost_fields = [
        cost("room", "Room rent + nursing & service charges"),
        cost("icu", "ICU charges"),
        cost("ot", "OT charges"),
        cost("professional_fees", "Professional fees (surgeon, anaesthetist, consultation)"),
        cost("medicines_consumables", "Medicines + consumables"),
        cost("investigations", "Investigations / diagnostics"),
        cost("implants", "Cost of implants"),
        _case_value("cost_total", "Total expected cost of hospitalisation",
                    f"₹{format_inr(total)}" if total else None, required=True),
    ]

    sections: list[dict[str, Any]] = [
        {"title": "Patient & policy", "fields": patient_fields},
        {"title": "Treating doctor & diagnosis", "fields": doctor_fields},
        {"title": "Admission", "fields": admission_fields},
        {"title": "Past history", "fields": history_fields},
        {"title": "Cost estimate", "fields": cost_fields},
    ]
    missing = [
        f"{section['title']}: {field['label']}"
        for section in sections
        for field in section["fields"]
        if field["required"] and field["source"] == "missing"
    ]
    return {
        "form_version": FORM_VERSION,
        "case_id": case.case_code,
        "sections": sections,
        "missing_required": missing,
        "attachments": _attachments(session, case, patient),
        "disclaimer": (
            "Illustrative mapping of the IRDAI cashless request form — confirm the current "
            "form and document list with each insurer/TPA. Not a submission."
        ),
    }


def _attachments(
    session: Session, case: AuthorizationCase, patient: Patient | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in build_case_checklist(session, case):
        if item.group != GROUP_DOCUMENTS:
            continue
        out.append(
            {
                "label": item.label,
                "status": "SUPPORTED" if item.status == "SUPPORTED" else "MISSING",
                "required": item.required,
                "citations": [citation.as_dict() for citation in item.citations],
            }
        )
    if patient is not None:
        investigations = [
            doc for doc in _patient_documents(session, patient)
            if doc.document_type in {"lab_result", "investigation_report", "imaging_report"}
        ]
        citations = _doc_citations(session, investigations[:3])
        out.append(
            {
                "label": "Investigation reports supporting diagnosis",
                "status": "SUPPORTED" if citations else "MISSING",
                "required": True,
                "citations": citations,
            }
        )
    return out


# --------------------------------------------------------------------------- discharge


def _patient_documents(session: Session, patient: Patient) -> list[Document]:
    return list(
        session.scalars(
            select(Document)
            .where(Document.patient_id == patient.id)
            .order_by(Document.created_at.desc(), Document.document_code.desc())
        ).all()
    )


def _doc_citations(session: Session, documents: Sequence[Document]) -> list[dict[str, Any]]:
    grouped = chunks_by_document(session, [doc.id for doc in documents])
    citations: list[dict[str, Any]] = []
    for doc in documents:
        chunks = grouped.get(doc.id) or []
        if not chunks:
            continue
        citations.append(
            {
                "document_id": doc.document_code,
                "chunk_id": chunks[0].chunk_code,
                "source": doc.document_type,
                "excerpt": chunks[0].content.strip()[:EXCERPT_MAX],
                "date": iso(doc.created_at),
            }
        )
    return citations


def _line_value(text: str, labels: Sequence[str]) -> str:
    for line in text.splitlines():
        for label in labels:
            match = re.match(rf"\s*{label}\s*[:\-]\s*(.+)$", line, re.I)
            if match:
                return match.group(1).strip()
    return ""


def normalize_icd(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _tokens(text: str) -> set[str]:
    stop = {"of", "the", "and", "with", "for", "left", "right", "acute", "a", "in", "on", "to",
            "under", "anaesthesia", "anesthesia", "eye", "status", "post"}
    cleaned = re.sub(r"\([^)]*\)", " ", (text or "").lower())
    cleaned = _ICD.sub(" ", cleaned.upper()).lower()
    return {tok for tok in re.findall(r"[a-z]{3,}", cleaned) if tok not in stop}


def _similar(a: str, b: str) -> bool:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return False
    overlap = len(left & right) / max(1, min(len(left), len(right)))
    return overlap >= 0.5


def _discharge_documents(session: Session, patient: Patient) -> list[Document]:
    docs = _patient_documents(session, patient)
    found = [doc for doc in docs if "discharge" in str(doc.document_type or "").lower()]
    if found:
        return found
    return [doc for doc in docs if "discharge summary" in (doc.content or "").lower()]


def _bill_amount(document: Document) -> int | None:
    meta = document.document_metadata or {}
    for key in ("total_inr", "net_payable_inr", "amount_inr"):
        raw = meta.get(key)
        if raw not in (None, ""):
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    for line in (document.content or "").splitlines():
        if re.search(r"total|net payable|grand", line, re.I):
            match = _AMOUNT.search(line)
            if match:
                return int(match.group(1).replace(",", ""))
    return None


def discharge_check(session: Session, case: AuthorizationCase) -> dict[str, Any]:
    patient = session.get(Patient, case.patient_id)
    findings: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str, *, expected: Any = None, found: Any = None,
            citations: list[dict[str, Any]] | None = None) -> None:
        findings.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "expected": None if expected is None else str(expected),
                "found": None if found is None else str(found),
                "citations": citations or [],
            }
        )

    if patient is None:
        add("blocker", "PATIENT_MISSING", "Case has no patient record.")
        return {"status": "blockers", "findings": findings}

    treatment = str(case.proposed_treatment or case.procedure or "")
    summaries = _discharge_documents(session, patient)
    summary = summaries[0] if summaries else None
    summary_cites = _doc_citations(session, [summary]) if summary is not None else []
    text = summary.content if summary is not None else ""

    if summary is None:
        add("blocker", "DISCHARGE_SUMMARY_MISSING", "Discharge summary is not on file.",
            expected="Discharge summary signed by the treating doctor", found="none")
    else:
        add("info", "DISCHARGE_SUMMARY_PRESENT", "Discharge summary is on file.",
            citations=summary_cites)
        dx_line = _line_value(text, ("final diagnosis", "discharge diagnosis", "diagnosis at discharge",
                                     "diagnosis"))
        icd_match = _ICD.search(dx_line) or _ICD.search(text)
        found_icd = icd_match.group(1) if icd_match else ""
        pre_icd = str(case.icd10_code or "")
        expected_dx = f"{case.provisional_diagnosis or ''} ({pre_icd})".strip()
        if pre_icd and found_icd and normalize_icd(pre_icd) != normalize_icd(found_icd):
            add("blocker", "DIAGNOSIS_MISMATCH",
                "Discharge diagnosis differs from pre-auth diagnosis",
                expected=expected_dx, found=dx_line or found_icd, citations=summary_cites)
        elif dx_line and case.provisional_diagnosis and not found_icd and not _similar(
            dx_line, str(case.provisional_diagnosis)
        ):
            add("warning", "DIAGNOSIS_MISMATCH",
                "Discharge diagnosis wording differs from pre-auth diagnosis",
                expected=expected_dx, found=dx_line, citations=summary_cites)
        elif not dx_line and not found_icd:
            add("warning", "DIAGNOSIS_NOT_FOUND",
                "Could not find a final diagnosis line in the discharge summary.",
                expected=expected_dx, citations=summary_cites)
        else:
            add("info", "DIAGNOSIS_MATCH", "Discharge diagnosis matches the pre-auth diagnosis.",
                expected=expected_dx, found=dx_line or found_icd, citations=summary_cites)

        procedure_line = _line_value(text, ("procedure performed", "surgery performed",
                                            "procedure done", "procedure", "operation"))
        if _SURGICAL.search(treatment):
            if not procedure_line:
                chart_procs = [p.name for p in list_procedures(session, patient.id)]
                if any(_similar(name, treatment) for name in chart_procs):
                    add("info", "PROCEDURE_MATCH", "Procedure recorded in the chart matches.",
                        expected=treatment)
                else:
                    add("warning", "PROCEDURE_NOT_DOCUMENTED",
                        "Discharge summary does not state the procedure performed.",
                        expected=treatment, citations=summary_cites)
            elif not _similar(procedure_line, treatment):
                add("warning", "PROCEDURE_MISMATCH",
                    "Procedure performed differs from the approved procedure.",
                    expected=treatment, found=procedure_line, citations=summary_cites)
            else:
                add("info", "PROCEDURE_MATCH", "Procedure performed matches the approved procedure.",
                    expected=treatment, found=procedure_line, citations=summary_cites)

    docs = _patient_documents(session, patient)
    bills = [doc for doc in docs if "bill" in str(doc.document_type or "").lower()]
    approved = case.approved_amount_inr
    if not bills:
        add("blocker", "FINAL_BILL_MISSING", "Final hospital bill is not on file.",
            expected="Final bill with itemised breakup", found="none")
    else:
        bill = bills[0]
        amount = _bill_amount(bill)
        cites = _doc_citations(session, [bill])
        if amount is None:
            add("warning", "BILL_AMOUNT_UNREADABLE", "Could not read the total on the final bill.",
                citations=cites)
        elif approved is None:
            add("warning", "APPROVED_AMOUNT_MISSING",
                "No approved amount is recorded to compare against the final bill.",
                found=f"₹{format_inr(amount)}", citations=cites)
        elif amount > approved:
            add("warning", "BILL_EXCEEDS_APPROVED",
                f"Final bill exceeds the approved amount (incl. enhancements) by "
                f"₹{format_inr(amount - approved)} — request enhancement or collect the "
                "difference as per policy.",
                expected=f"≤ ₹{format_inr(approved)}", found=f"₹{format_inr(amount)}",
                citations=cites)
        else:
            add("info", "BILL_WITHIN_APPROVED", "Final bill is within the approved amount.",
                expected=f"≤ ₹{format_inr(approved)}", found=f"₹{format_inr(amount)}",
                citations=cites)

    admitted = aware(case.admitted_at)
    expected_out = aware(case.expected_discharge_at)
    discharge_on = _line_value(text, ("date of discharge", "discharge date")) if text else ""
    actual_out = _parse_date(discharge_on) or (aware(summary.created_at) if summary else None)
    if admitted and expected_out and actual_out:
        expected_days = max(1, round((expected_out - admitted).total_seconds() / 86400))
        actual_days = max(1, round((actual_out - admitted).total_seconds() / 86400))
        if actual_days > expected_days + 1:
            add("warning", "LOS_EXCEEDS_EXPECTED",
                "Length of stay is longer than estimated in the pre-auth — explain in the "
                "discharge summary.", expected=f"{expected_days} day(s)",
                found=f"{actual_days} day(s)")
        else:
            add("info", "LOS_AS_EXPECTED", "Length of stay is in line with the estimate.",
                expected=f"{expected_days} day(s)", found=f"{actual_days} day(s)")

    investigations = [doc for doc in docs if doc.document_type in
                      {"lab_result", "investigation_report", "imaging_report"}]
    if not investigations:
        add("warning", "INVESTIGATION_REPORTS_MISSING",
            "No investigation reports are on file to attach with the discharge request.")
    if _IMPLANT.search(treatment):
        implant_docs = [
            doc for doc in docs
            if re.search(r"implant|sticker|invoice", str(doc.document_type or ""), re.I)
            or re.search(r"implant (?:sticker|invoice)|iol sticker|stent invoice|sticker",
                         doc.content or "", re.I)
        ]
        if implant_docs:
            add("info", "IMPLANT_INVOICE_PRESENT", "Implant invoice / sticker is on file.",
                citations=_doc_citations(session, implant_docs[:1]))
        else:
            add("blocker", "IMPLANT_INVOICE_MISSING",
                "Implant invoice / barcode sticker is required for implant cases.",
                expected="Implant invoice + sticker", found="none")

    severities = {item["severity"] for item in findings}
    status = "blockers" if "blocker" in severities else "warnings" if "warning" in severities else "ok"
    return {"status": status, "findings": findings}


def _parse_date(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    for fmt, width in (
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
        ("%d-%m-%Y %H:%M", 16),
        ("%d-%m-%Y", 10),
        ("%d/%m/%Y", 10),
    ):
        try:
            return datetime.strptime(value[:width], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
