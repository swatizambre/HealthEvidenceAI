"""Illustrative India cashless checklists + deterministic TPA desk demo cases (synthetic only).

Runs only inside the synthetic seed (``persist_dataset``). It re-labels catalog
filler rows in place so dataset counts stay stable (100 patients / 20 policies /
20 cases): POL-000002..POL-000008 become India checklists and PA-000005..PA-000016
become desk cases across every stage. Times are offsets from "now" so the desk
shows overdue / due-soon / plenty clocks whenever the demo is started.

All insurer, TPA, doctor and patient names are synthetic. Checklists are
illustrative — confirm with each insurer/TPA. Never Medicare / US payer policies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    AuthorizationCase,
    CaseQuery,
    ClinicalNote,
    Document,
    ImagingStudy,
    InsurancePolicy,
    LabResult,
    Patient,
    PolicyCriterion,
    Procedure,
    ReviewRun,
)

logger = logging.getLogger("healthevidence.tpa_seed")

PAYER_LABEL = "Illustrative — confirm with each insurer/TPA"
SENIOR_ACTOR = "dr.kulkarni (senior clinician, synthetic)"
DESK_ACTOR = "tpa-desk (synthetic)"

# Synthetic Indian payer labels used wherever the Synthea catalog would show US payers.
INDIAN_PAYER_LABELS: tuple[str, ...] = (
    "Star Health (synthetic)",
    "ICICI Lombard (synthetic)",
    "HDFC ERGO (synthetic)",
    "Niva Bupa (synthetic)",
    "New India Assurance (synthetic) via Medi Assist (synthetic)",
    "Care Health (synthetic)",
    "Bajaj Allianz (synthetic) via Health India TPA (synthetic)",
    "PM-JAY (synthetic)",
    "CGHS (synthetic)",
)


def indian_payer_label(index: int) -> str:
    return INDIAN_PAYER_LABELS[index % len(INDIAN_PAYER_LABELS)]


def _kw(code: str, description: str, phrases: list[str], *, group: str = "clinical",
        missing: str = "", required: bool = True, document_types: list[str] | None = None,
        ) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "type": "keyword",
        "required_any": phrases,
        "negation_any": [],
        "missing_label": missing or description,
        "group": group,
        "required": required,
    }
    if document_types:
        rule["document_types"] = document_types
    return {"code": code, "description": description, "rule": rule}


# Accepted document types for documents-group criteria (substring match on document_type).
_IMAGING_DOCS = ["radiology_report", "imaging_report"]
_REPORT_DOCS = ["investigation_report", "radiology_report", "imaging_report"]


def _lab(code: str, description: str, test_name: str, *, missing: str = "") -> dict[str, Any]:
    return {
        "code": code,
        "description": description,
        "rule": {
            "type": "lab_test",
            "test_name": test_name,
            "presence": True,
            "missing_label": missing or f"{test_name} result",
            "group": "clinical",
            "required": True,
        },
    }


@dataclass(frozen=True)
class ChecklistSpec:
    policy_code: str
    key: str
    title: str
    procedure: str
    match: tuple[str, ...]
    criteria: tuple[dict[str, Any], ...]


INDIA_CHECKLISTS: tuple[ChecklistSpec, ...] = (
    ChecklistSpec(
        "POL-000002", "cataract", "Cataract surgery (phaco + IOL) — cashless checklist",
        "Phacoemulsification with foldable IOL", ("cataract", "phaco", "iol"),
        (
            _kw("CRIT-IN-CAT-01", "Visual acuity documented for the operated eye",
                ["visual acuity"]),
            _kw("CRIT-IN-CAT-02", "Cataract grading / slit-lamp findings documented",
                ["nuclear sclerosis", "posterior subcapsular cataract", "mature cataract",
                 "cataract grade"]),
            _lab("CRIT-IN-CAT-03", "Pre-operative blood sugar recorded", "Random blood sugar"),
            _kw("CRIT-IN-CAT-04", "A-scan biometry report with IOL power",
                ["biometry report", "a-scan biometry"], group="documents",
                document_types=_REPORT_DOCS),
            _kw("CRIT-IN-CAT-05", "IOL sticker / invoice (needed at discharge)",
                ["iol sticker", "lens sticker"], group="documents", required=False,
                document_types=["implant_invoice"]),
        ),
    ),
    ChecklistSpec(
        "POL-000003", "tkr", "Total knee replacement — cashless checklist",
        "Total knee replacement", ("knee replacement", "tkr", "arthroplasty"),
        (
            _kw("CRIT-IN-TKR-01", "Osteoarthritis of the knee documented with grade",
                ["osteoarthritis"]),
            _kw("CRIT-IN-TKR-02", "Failed conservative management documented",
                ["physiotherapy", "failed conservative management"]),
            _lab("CRIT-IN-TKR-03", "Pre-operative haemoglobin recorded", "Hemoglobin"),
            _kw("CRIT-IN-TKR-04", "Pre-anaesthetic check / fitness for surgery",
                ["fit for surgery", "pre-anaesthetic check", "pac done"]),
            _kw("CRIT-IN-TKR-05", "Weight-bearing X-ray knee report",
                ["x-ray knee", "weight-bearing x-ray"], group="documents",
                document_types=_IMAGING_DOCS),
            _kw("CRIT-IN-TKR-06", "Implant quotation (make, model, MRP)",
                ["implant quotation", "implant quote"], group="documents",
                document_types=["implant_quote"]),
        ),
    ),
    ChecklistSpec(
        "POL-000004", "appendectomy", "Laparoscopic appendectomy — cashless checklist",
        "Laparoscopic appendectomy", ("append",),
        (
            _kw("CRIT-IN-APP-01", "Clinical findings of appendicitis (RIF pain / tenderness)",
                ["right iliac fossa", "rif tenderness", "mcburney"]),
            _lab("CRIT-IN-APP-02", "Total leucocyte count recorded", "Total leucocyte count"),
            _kw("CRIT-IN-APP-03", "Surgeon's admission note with operative plan",
                ["laparoscopic appendectomy"]),
            _kw("CRIT-IN-APP-04", "USG / CT abdomen report supporting appendicitis",
                ["usg abdomen", "ultrasound abdomen", "ct abdomen"], group="documents",
                document_types=_IMAGING_DOCS),
        ),
    ),
    ChecklistSpec(
        "POL-000005", "lscs", "Lower segment caesarean section (LSCS) — cashless checklist",
        "Lower segment caesarean section", ("lscs", "caesarean", "cesarean", "c-section"),
        (
            _kw("CRIT-IN-LSCS-01", "Obstetric score (G/P/L/A) and gestation documented",
                ["obstetric score", "gravida"]),
            _kw("CRIT-IN-LSCS-02", "Indication for caesarean documented",
                ["previous lscs", "fetal distress", "breech", "cephalopelvic disproportion",
                 "non-progress of labour"]),
            _lab("CRIT-IN-LSCS-03", "Haemoglobin recorded", "Hemoglobin"),
            _kw("CRIT-IN-LSCS-04", "Antenatal ultrasound (growth scan) report",
                ["obstetric ultrasound", "antenatal usg", "growth scan"], group="documents",
                document_types=_IMAGING_DOCS),
            _kw("CRIT-IN-LSCS-05", "ANC card / antenatal record",
                ["anc card", "antenatal record"], group="documents",
                document_types=["anc_card", "antenatal_record"]),
        ),
    ),
    ChecklistSpec(
        "POL-000006", "ptca", "Coronary angioplasty (PTCA) — cashless checklist",
        "Coronary angioplasty (PTCA) with stent", ("ptca", "angioplasty", "stent"),
        (
            _kw("CRIT-IN-PTCA-01", "ECG findings documented", ["ecg"]),
            _lab("CRIT-IN-PTCA-02", "Cardiac biomarker (Troponin I) recorded", "Troponin I"),
            _kw("CRIT-IN-PTCA-03", "Diagnosis of ACS / CAD documented",
                ["stemi", "nstemi", "myocardial infarction", "unstable angina",
                 "coronary artery disease"]),
            _kw("CRIT-IN-PTCA-04", "Coronary angiography (CAG) report",
                ["coronary angiography report", "cag report"], group="documents",
                document_types=_REPORT_DOCS),
            _kw("CRIT-IN-PTCA-05", "2D echo report", ["2d echo", "echocardiography"],
                group="documents", document_types=_REPORT_DOCS),
            _kw("CRIT-IN-PTCA-06", "Stent invoice / sticker (needed at discharge)",
                ["stent invoice", "stent sticker"], group="documents", required=False,
                document_types=["implant_invoice"]),
        ),
    ),
    ChecklistSpec(
        "POL-000007", "febrile", "Acute febrile illness (medical management) — cashless checklist",
        "Medical management of acute febrile illness",
        ("fever", "febrile", "dengue", "malaria", "typhoid", "medical management"),
        (
            _kw("CRIT-IN-AFI-01", "Fever history and duration documented",
                ["fever for", "febrile"]),
            _kw("CRIT-IN-AFI-02", "Indication for admission (warning signs) documented",
                ["warning signs", "thrombocytopenia", "persistent vomiting", "hypotension"]),
            _lab("CRIT-IN-AFI-03", "Platelet count recorded", "Platelet count"),
            _kw("CRIT-IN-AFI-04", "Fever work-up (dengue NS1 / malaria / typhoid test)",
                ["dengue ns1", "malaria antigen", "peripheral smear", "widal"]),
            _kw("CRIT-IN-AFI-05", "CBC report", ["complete blood count", "cbc report"],
                group="documents", document_types=[*_REPORT_DOCS, "lab_result"]),
        ),
    ),
    ChecklistSpec(
        "POL-000008", "rta", "Road traffic injury (with MLC) — cashless checklist",
        "Fracture fixation after road traffic injury",
        ("rta", "road traffic", "accident", "injury", "fracture", "orif"),
        (
            _kw("CRIT-IN-RTA-01", "Mechanism and time of injury documented",
                ["road traffic accident", "rta"]),
            _kw("CRIT-IN-RTA-02", "Alcohol / intoxication status documented",
                ["breath alcohol", "alcohol test"]),
            _kw("CRIT-IN-RTA-03", "Injury details documented", ["fracture"]),
            _kw("CRIT-IN-RTA-04", "MLC copy / police intimation (FIR)",
                ["mlc number", "medico-legal case", "police intimation", "fir"],
                group="documents", document_types=["mlc_copy", "police_intimation", "fir_copy"]),
            _kw("CRIT-IN-RTA-05", "X-ray / CT report of the injured part", ["x-ray", "ct scan"],
                group="documents", document_types=_IMAGING_DOCS),
        ),
    ),
)


def checklist_for_treatment(treatment: str) -> str | None:
    """Policy code of the illustrative checklist matching free-text treatment."""
    text = (treatment or "").lower()
    for spec in INDIA_CHECKLISTS:
        if any(token in text for token in spec.match):
            return spec.policy_code
    return None


def _policy_content(spec: ChecklistSpec) -> str:
    groups = {"clinical": [], "documents": []}  # type: dict[str, list[str]]
    for item in spec.criteria:
        groups[str(item["rule"].get("group", "clinical"))].append(str(item["description"]))
    return (
        f"India cashless pre-authorization checklist: {spec.title}. {PAYER_LABEL}. "
        "Form items: insurer/TPA, policy number, provisional diagnosis with ICD-10, proposed "
        "treatment, treating doctor, admission date/time, cost estimate. "
        f"Clinical items: {'; '.join(groups['clinical'])}. "
        f"Documents: {'; '.join(groups['documents'])}. "
        "Prepares paperwork only; the insurer/TPA decides. "
        f"Marker {spec.policy_code}."
    )


# --------------------------------------------------------------------------- demo cases


@dataclass(frozen=True)
class DocSpec:
    document_type: str
    content: str
    offset_h: float
    metadata: dict[str, Any] = field(default_factory=dict)
    as_note: bool = True


@dataclass(frozen=True)
class QuerySpec:
    text: str
    raised_h: float
    due_hours: float = 24.0
    responded_h: float | None = None
    response: str = ""
    resume_stage: str = "sent"


@dataclass(frozen=True)
class CaseSpec:
    case_code: str
    policy_code: str
    name: str
    sex: str
    ages: tuple[int, int]
    payer_type: str
    insurer: str
    tpa: str
    policy_number: str
    admission_type: str
    admitted_h: float
    expected_discharge_h: float
    doctor: str
    diagnosis: str
    icd10: str
    treatment: str
    estimate: int
    costs: dict[str, int]
    stage: str
    prep_h: float
    review: str  # acknowledged | awaiting_senior | none
    review_h: float | None = None
    sent_h: float | None = None
    approved_h: float | None = None
    approved_amount: int | None = None
    enhancement_h: float | None = None
    revised_estimate: int | None = None
    enhancement_reason: str = ""
    discharge_h: float | None = None
    closed_h: float | None = None
    conditions: tuple[str, ...] = ()
    labs: tuple[tuple[str, str, str], ...] = ()
    imaging: tuple[tuple[str, str, str], ...] = ()
    procedures: tuple[str, ...] = ()
    docs: tuple[DocSpec, ...] = ()
    queries: tuple[QuerySpec, ...] = ()
    form_extra: dict[str, Any] = field(default_factory=dict)


def _day(now: datetime, offset_h: float) -> str:
    return (now + timedelta(hours=offset_h)).strftime("%Y-%m-%d")


def demo_case_specs(now: datetime) -> tuple[CaseSpec, ...]:
    """Twelve deterministic desk cases (₹, IST-realistic) spanning every stage."""
    return (
        CaseSpec(
            "PA-000005", "POL-000002", "Sunanda Kulkarni", "female", (55, 80),
            "insurer", "Star Health (synthetic)", "", "SHI-P-2026-004417",
            "planned", -6, 18, "Dr. Meera Joshi (Ophthalmology)",
            "Senile nuclear cataract, right eye", "H25.1",
            "Phacoemulsification with foldable IOL, right eye", 32000,
            {"room": 4000, "ot": 9000, "professional_fees": 8000, "medicines_consumables": 3500,
             "investigations": 1500, "implants": 6000},
            "approved", prep_h=-9.0, review="acknowledged", review_h=-8.45, sent_h=-8.0,
            approved_h=-7.5, approved_amount=28000,
            conditions=("Type 2 diabetes mellitus (disorder)",),
            labs=(("Random blood sugar", "148", "mg/dL"),),
            docs=(
                DocSpec("clinical_note",
                        "Ophthalmology OPD note\n"
                        "Presenting complaints: gradual painless diminution of vision right eye "
                        "for 1 year\n"
                        "Visual acuity: RE 6/36, LE 6/12 (Snellen)\n"
                        "Slit lamp: nuclear sclerosis grade 3 right eye\n"
                        "Known type 2 diabetes mellitus for 6 years on metformin\n"
                        "Plan: phacoemulsification with foldable IOL right eye under local "
                        "anaesthesia", -30),
                DocSpec("investigation_report",
                        "A-scan biometry report: axial length 23.42 mm, K1 43.75 D, K2 44.25 D, "
                        "IOL power +21.5 D (SRK/T)", -29),
            ),
            form_extra={"room_type": "Day care", "illness_duration": "1 year"},
        ),
        CaseSpec(
            "PA-000006", "POL-000003", "Vasant Shinde", "male", (55, 80),
            "tpa", "New India Assurance (synthetic)", "Medi Assist (synthetic)",
            "NIA-31020034-2026", "planned", 20, 140, "Dr. Anil Deshpande (Orthopaedics)",
            "Primary osteoarthritis, right knee (KL grade 4)", "M17.1",
            "Total knee replacement, right knee", 285000,
            {"room": 30000, "ot": 45000, "professional_fees": 60000,
             "medicines_consumables": 35000, "investigations": 10000, "implants": 105000},
            "draft", prep_h=-5.0, review="awaiting_senior", review_h=-4.6,
            conditions=("Essential hypertension (disorder)",
                        "Primary osteoarthritis of knee (disorder)"),
            labs=(("Hemoglobin", "12.8", "g/dL"),),
            docs=(
                DocSpec("clinical_note",
                        "Orthopaedic OPD note\n"
                        "Presenting complaints: pain right knee for 4 years, difficulty climbing "
                        "stairs\n"
                        "Diagnosis: primary osteoarthritis right knee, Kellgren-Lawrence grade 4\n"
                        "Conservative management: physiotherapy and NSAIDs for 6 months with "
                        "little relief\n"
                        "Known hypertension for 10 years on amlodipine\n"
                        "Plan: total knee replacement right knee", -50),
                DocSpec("radiology_report",
                        "X-ray knee report (standing AP and lateral, weight-bearing): severe "
                        "medial joint space narrowing, osteophytes, subchondral sclerosis right "
                        "knee", -49),
            ),
            form_extra={"room_type": "Twin sharing", "illness_duration": "4 years"},
        ),
        CaseSpec(
            "PA-000007", "POL-000007", "Rahul Gaikwad", "male", (18, 45),
            "pmjay", "PM-JAY / MJPJAY (synthetic)", "", "PMJAY-27-0051-8832",
            "emergency", -4, 68, "Dr. Sanjay Patil (General Medicine)",
            "Dengue fever with warning signs", "A97.1",
            "Medical management — IV fluids and platelet monitoring", 45000,
            {"room": 12000, "professional_fees": 8000, "medicines_consumables": 15000,
             "investigations": 10000},
            "ready_to_send", prep_h=-200 / 60, review="acknowledged", review_h=-2.6,
            labs=(("Platelet count", "68000", "/cumm"),),
            docs=(
                DocSpec("clinical_note",
                        "Emergency admission note\n"
                        "Presenting complaints: fever for 4 days with body ache and vomiting\n"
                        "Warning signs: persistent vomiting, platelet count falling\n"
                        "Dengue NS1 antigen: positive\n"
                        "Admitted under general medicine for IV fluids and monitoring", -3.8),
                DocSpec("investigation_report",
                        "Complete blood count report: haemoglobin 14.1 g/dL, TLC 3,200 /cumm, "
                        "platelet count 68,000 /cumm", -3.5),
            ),
            form_extra={"room_type": "General ward", "illness_duration": "4 days",
                        "route_of_drug_administration": "Intravenous"},
        ),
        CaseSpec(
            "PA-000008", "POL-000004", "Priya Nair", "female", (18, 40),
            "insurer", "ICICI Lombard (synthetic)", "", "ICL-4128-77-2026",
            "emergency", -3, 45, "Dr. Kiran Rao (General Surgery)",
            "Acute appendicitis", "K35.8", "Laparoscopic appendectomy", 85000,
            {"room": 10000, "ot": 20000, "professional_fees": 25000,
             "medicines_consumables": 20000, "investigations": 10000},
            "sent", prep_h=-2.5, review="acknowledged", review_h=-1.9, sent_h=-25 / 60,
            labs=(("Total leucocyte count", "14200", "/cumm"),),
            docs=(
                DocSpec("clinical_note",
                        "Surgical admission note\n"
                        "Presenting complaints: pain abdomen for 1 day, periumbilical shifting to "
                        "right iliac fossa, with vomiting\n"
                        "Examination: RIF tenderness, rebound tenderness at McBurney point\n"
                        "Plan: laparoscopic appendectomy under general anaesthesia", -2.9),
                DocSpec("radiology_report",
                        "USG abdomen report: non-compressible aperistaltic tubular structure in "
                        "right iliac fossa, 9 mm diameter, suggestive of acute appendicitis", -2.7),
            ),
            form_extra={"room_type": "Semi-private", "illness_duration": "1 day"},
        ),
        CaseSpec(
            "PA-000009", "POL-000006", "Mahesh Iyer", "male", (45, 75),
            "tpa", "HDFC ERGO (synthetic)", "Paramount Health Services (synthetic)",
            "HE-2856-0091-4410", "emergency", -5, 67, "Dr. Neha Kulkarni (Cardiology)",
            "Acute anterior wall STEMI", "I21.0",
            "Coronary angioplasty (PTCA) with drug-eluting stent to LAD", 245000,
            {"room": 15000, "icu": 40000, "ot": 35000, "professional_fees": 30000,
             "medicines_consumables": 25000, "investigations": 15000, "implants": 85000},
            "sent", prep_h=-3.0, review="acknowledged", review_h=-2.45, sent_h=-75 / 60,
            conditions=("Type 2 diabetes mellitus (disorder)", "Essential hypertension (disorder)"),
            labs=(("Troponin I", "4.8", "ng/mL"),),
            docs=(
                DocSpec("clinical_note",
                        "Cardiology emergency note\n"
                        "Presenting complaints: retrosternal chest pain for 3 hours with "
                        "sweating\n"
                        "ECG: ST elevation in V1-V4, anterior wall STEMI\n"
                        "Known diabetes mellitus for 8 years and hypertension for 5 years\n"
                        "Plan: primary PTCA to LAD", -4.8),
                DocSpec("investigation_report",
                        "Coronary angiography report: 95% thrombotic occlusion of proximal LAD, "
                        "TIMI 1 flow; LCx and RCA normal", -4.2),
                DocSpec("investigation_report",
                        "2D echo report: regional wall motion abnormality in LAD territory, "
                        "LVEF 40%", -4.0),
            ),
            form_extra={"room_type": "ICCU", "illness_duration": "3 hours"},
        ),
        CaseSpec(
            "PA-000010", "POL-000005", "Ayesha Shaikh", "female", (22, 38),
            "tpa", "Niva Bupa (synthetic)", "Medi Assist (synthetic)", "NB-3022-1187-2026",
            "planned", -6, 66, "Dr. Smita Bhosale (Obstetrics & Gynaecology)",
            "Previous LSCS, term pregnancy (G2P1L1)", "O34.2",
            "Elective lower segment caesarean section (LSCS)", 95000,
            {"room": 18000, "ot": 22000, "professional_fees": 30000,
             "medicines_consumables": 15000, "investigations": 10000},
            "query", prep_h=-23.5, review="acknowledged", review_h=-22.9, sent_h=-22,
            labs=(("Hemoglobin", "11.2", "g/dL"),),
            docs=(
                DocSpec("clinical_note",
                        "Obstetric admission note\n"
                        "Obstetric score: G2P1L1A0, 38 weeks gestation\n"
                        "Indication: previous LSCS with inadequate scar interval\n"
                        "ANC card reviewed: 9 antenatal visits\n"
                        "Plan: elective LSCS", -24),
                DocSpec("anc_card",
                        "ANC card: G2P1L1A0, 9 antenatal visits, TT 2 doses, blood group B "
                        "positive", -24.5, as_note=False),
            ),
            queries=(
                QuerySpec("Please share the antenatal ultrasound (growth scan) report and the "
                          "previous LSCS discharge summary.", raised_h=-20, due_hours=24),
            ),
            form_extra={"room_type": "Semi-private", "gpla": "G2 P1 L1 A0",
                        "expected_delivery_date": _day(now, 72)},
        ),
        CaseSpec(
            "PA-000011", "POL-000008", "Imran Qureshi", "male", (20, 50),
            "tpa", "Bajaj Allianz (synthetic)", "Health India TPA (synthetic)",
            "BA-OG-26-1801-4402", "emergency", -30, 66, "Dr. Rohan Mehta (Orthopaedics)",
            "Closed fracture shaft of right femur", "S72.3",
            "Open reduction and internal fixation (ORIF) with intramedullary nail, right femur",
            175000,
            {"room": 20000, "ot": 30000, "professional_fees": 40000,
             "medicines_consumables": 20000, "investigations": 10000, "implants": 55000},
            "query", prep_h=-29, review="acknowledged", review_h=-28.4, sent_h=-28,
            labs=(("Hemoglobin", "12.1", "g/dL"),),
            imaging=(("XR", "Right femur", "Displaced fracture shaft of right femur"),),
            docs=(
                DocSpec("clinical_note",
                        "Casualty note\n"
                        "Alleged history of road traffic accident (two-wheeler skid) at 21:30\n"
                        "MLC number MLC/2026/1187 registered; police intimation sent\n"
                        "Breath alcohol test done at casualty\n"
                        "X-ray right thigh: displaced fracture shaft of femur", -30),
                DocSpec("radiology_report",
                        "X-ray right femur report (AP and lateral): displaced transverse "
                        "fracture of the mid-shaft of the right femur", -29.5),
            ),
            queries=(
                QuerySpec("Submit a copy of the MLC / FIR and the breath alcohol test report.",
                          raised_h=-23.5, due_hours=24),
            ),
            form_extra={"room_type": "General ward", "injury_date": _day(now, -31),
                        "injury_cause": "Two-wheeler skid on Pune–Satara highway",
                        "mlc_number": "MLC/2026/1187",
                        "police_report": "Intimated to Sinhagad Road police station",
                        "alcohol_involved": "Breath alcohol test done — report awaited"},
        ),
        CaseSpec(
            "PA-000012", "POL-000007", "Lakshmi Reddy", "female", (30, 60),
            "insurer", "Care Health (synthetic)", "", "CH-7781-2290-2026",
            "emergency", -72, 24, "Dr. Sanjay Patil (General Medicine)",
            "Plasmodium falciparum malaria with thrombocytopenia", "B50.9",
            "Medical management — IV artesunate and supportive care", 72000,
            {"room": 16000, "icu": 20000, "professional_fees": 12000,
             "medicines_consumables": 14000, "investigations": 10000},
            "approved", prep_h=-71.5, review="acknowledged", review_h=-71.0, sent_h=-70.5,
            approved_h=-28, approved_amount=72000, enhancement_h=-30, revised_estimate=72000,
            enhancement_reason="ICU stay for 2 days due to severe thrombocytopenia",
            labs=(("Platelet count", "42000", "/cumm"),),
            docs=(
                DocSpec("clinical_note",
                        "Emergency admission note\n"
                        "Presenting complaints: high grade fever for 5 days with chills and "
                        "rigors\n"
                        "Warning signs: thrombocytopenia, platelet count 42,000\n"
                        "Peripheral smear: Plasmodium falciparum ring forms seen", -71.8),
                DocSpec("investigation_report",
                        "Complete blood count report: Hb 10.4 g/dL, TLC 5,600 /cumm, platelet "
                        "count 42,000 /cumm", -71.6),
            ),
            queries=(
                QuerySpec("Share the platelet trend for the last 48 hours.", raised_h=-60,
                          due_hours=24, responded_h=-58,
                          response="Platelet trend attached: 42,000 → 38,000 → 51,000 /cumm."),
            ),
            form_extra={"room_type": "General ward", "illness_duration": "5 days",
                        "route_of_drug_administration": "Intravenous"},
        ),
        CaseSpec(
            "PA-000013", "POL-000003", "Kusum Jadhav", "female", (58, 78),
            "cghs", "CGHS Pune (synthetic)", "", "CGHS-PNQ-118204",
            "planned", -48, 72, "Dr. Anil Deshpande (Orthopaedics)",
            "Primary osteoarthritis, left knee", "M17.1",
            "Total knee replacement, left knee", 190000,
            {"room": 25000, "ot": 40000, "professional_fees": 35000,
             "medicines_consumables": 25000, "investigations": 10000, "implants": 55000},
            "enhancement", prep_h=-72, review="acknowledged", review_h=-71.4, sent_h=-70,
            approved_h=-44, approved_amount=190000, enhancement_h=-20 / 60,
            revised_estimate=235000,
            enhancement_reason="Constrained implant needed due to bone loss found intra-operatively",
            labs=(("Hemoglobin", "11.9", "g/dL"),),
            docs=(
                DocSpec("clinical_note",
                        "Orthopaedic OPD note\n"
                        "Diagnosis: primary osteoarthritis left knee, Kellgren-Lawrence grade 4\n"
                        "Conservative management: physiotherapy for 1 year\n"
                        "Pre-anaesthetic check: fit for surgery (ASA II)", -96),
                DocSpec("radiology_report",
                        "X-ray knee report (weight-bearing): tricompartmental osteoarthritis left "
                        "knee", -95),
                DocSpec("implant_quote",
                        "Implant quotation: cemented posterior-stabilised knee system, "
                        "MRP ₹1,05,000", -94),
            ),
            form_extra={"room_type": "Semi-private"},
        ),
        CaseSpec(
            "PA-000014", "POL-000004", "Arjun Kale", "male", (18, 45),
            "insurer", "Star Health (synthetic)", "", "SHI-P-2026-009812",
            "emergency", -108, -60, "Dr. Kiran Rao (General Surgery)",
            "Acute appendicitis", "K35.8", "Laparoscopic appendectomy", 85000,
            {"room": 10000, "ot": 20000, "professional_fees": 25000,
             "medicines_consumables": 20000, "investigations": 10000},
            "discharge_pending", prep_h=-107, review="acknowledged", review_h=-106.5,
            sent_h=-106, approved_h=-105, approved_amount=85000,
            labs=(("Total leucocyte count", "16800", "/cumm"),),
            procedures=("Laparoscopic appendectomy",),
            docs=(
                DocSpec("clinical_note",
                        "Surgical admission note\n"
                        "Presenting complaints: pain in right iliac fossa for 2 days with fever\n"
                        "Examination: RIF tenderness and guarding\n"
                        "Plan: laparoscopic appendectomy", -107.5),
                DocSpec("radiology_report",
                        "USG abdomen report: inflamed appendix 11 mm with periappendiceal "
                        "collection", -107.2),
                DocSpec("discharge_summary",
                        "Discharge summary\n"
                        f"Date of admission: {_day(now, -108)}\n"
                        f"Date of discharge: {_day(now, 0)}\n"
                        "Final diagnosis: Acute appendicitis with perforation and localised "
                        "peritonitis (K35.3)\n"
                        "Procedure performed: Laparoscopic appendectomy with peritoneal lavage\n"
                        "Condition at discharge: stable, tolerating orally", -1),
                DocSpec("final_bill",
                        "Final bill IP/2026/5521\nRoom rent and nursing: ₹16,000\nOT and "
                        "procedure: ₹28,000\nProfessional fees: ₹30,000\nMedicines and "
                        "consumables: ₹26,500\nInvestigations: ₹12,000\nTotal: ₹1,12,500",
                        -0.5, metadata={"total_inr": 112500}, as_note=False),
            ),
            form_extra={"room_type": "Semi-private"},
        ),
        CaseSpec(
            "PA-000015", "POL-000002", "Gopal Rao", "male", (60, 80),
            "insurer", "Star Health (synthetic)", "", "SHI-P-2026-011274",
            "planned", -8, -1, "Dr. Meera Joshi (Ophthalmology)",
            "Senile nuclear cataract, left eye", "H25.1",
            "Phacoemulsification with foldable IOL, left eye", 32000,
            {"room": 4000, "ot": 9000, "professional_fees": 8000, "medicines_consumables": 3500,
             "investigations": 1500, "implants": 6000},
            "discharge_sent", prep_h=-30, review="acknowledged", review_h=-29.5, sent_h=-29,
            approved_h=-27, approved_amount=30000, discharge_h=-1.0,
            labs=(("Random blood sugar", "112", "mg/dL"),),
            procedures=("Phacoemulsification with foldable IOL, left eye",),
            docs=(
                DocSpec("clinical_note",
                        "Ophthalmology OPD note\n"
                        "Visual acuity: LE 6/60, RE 6/9\n"
                        "Slit lamp: nuclear sclerosis grade 3 left eye\n"
                        "Plan: phacoemulsification with foldable IOL left eye", -31),
                DocSpec("investigation_report",
                        "A-scan biometry report: axial length 23.10 mm, IOL power +22.0 D", -30.5),
                DocSpec("discharge_summary",
                        "Discharge summary\n"
                        f"Date of discharge: {_day(now, -1)}\n"
                        "Final diagnosis: Senile nuclear cataract, left eye (H25.1)\n"
                        "Procedure performed: Phacoemulsification with foldable IOL, left eye\n"
                        "Condition at discharge: stable", -1.5),
                DocSpec("final_bill", "Final bill IP/2026/5590\nTotal: ₹29,500", -1.4,
                        metadata={"total_inr": 29500}, as_note=False),
                DocSpec("implant_invoice",
                        "IOL sticker: hydrophobic acrylic foldable IOL +22.0 D, lot 2026-118; "
                        "implant invoice ₹6,000", -2, as_note=False),
            ),
            form_extra={"room_type": "Day care"},
        ),
        CaseSpec(
            "PA-000016", "POL-000006", "Prakash Menon", "male", (50, 80),
            "insurer", "ICICI Lombard (synthetic)", "", "ICL-5530-12-2026",
            "emergency", -144, -48, "Dr. Neha Kulkarni (Cardiology)",
            "NSTEMI with double vessel disease", "I21.4",
            "Coronary angioplasty (PTCA) with drug-eluting stent to RCA", 210000,
            {"room": 15000, "icu": 35000, "ot": 30000, "professional_fees": 30000,
             "medicines_consumables": 20000, "investigations": 10000, "implants": 70000},
            "closed", prep_h=-143.5, review="acknowledged", review_h=-143, sent_h=-142.5,
            approved_h=-141.5, approved_amount=210000, discharge_h=-50, closed_h=-46,
            labs=(("Troponin I", "1.9", "ng/mL"),),
            procedures=("Coronary angioplasty (PTCA) with drug-eluting stent to RCA",),
            docs=(
                DocSpec("clinical_note",
                        "Cardiology note\nECG: ST depression in II, III, aVF\n"
                        "Diagnosis: NSTEMI, coronary artery disease (double vessel)", -143.8),
                DocSpec("investigation_report",
                        "Coronary angiography report: 90% stenosis mid RCA, 70% LCx", -143.6),
                DocSpec("investigation_report", "2D echo report: LVEF 50%, mild inferior "
                        "hypokinesia", -143.4),
                DocSpec("discharge_summary",
                        "Discharge summary\n"
                        f"Date of discharge: {_day(now, -50)}\n"
                        "Final diagnosis: NSTEMI with double vessel disease (I21.4)\n"
                        "Procedure performed: Coronary angioplasty (PTCA) with drug-eluting "
                        "stent to RCA", -51),
                DocSpec("final_bill", "Final bill IP/2026/5402\nTotal: ₹2,05,000", -50.5,
                        metadata={"total_inr": 205000}, as_note=False),
                DocSpec("implant_invoice", "Stent invoice: drug-eluting stent 3.0 x 28 mm, "
                        "stent sticker attached", -140, as_note=False),
            ),
            form_extra={"room_type": "ICCU"},
        ),
    )


# --------------------------------------------------------------------------- apply


def _age(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _pick_patients(
    session: Session, specs: tuple[CaseSpec, ...], *, org_id: str | None, today: date
) -> dict[str, Patient]:
    statement = select(Patient).where(Patient.patient_code > "PAT-000004").order_by(
        Patient.patient_code
    )
    if org_id:
        statement = statement.where(Patient.org_id == org_id)
    pool = list(session.scalars(statement).all())
    used: set[str] = set()
    chosen: dict[str, Patient] = {}
    for spec in specs:
        low, high = spec.ages
        candidates = [p for p in pool if p.id not in used and p.sex == spec.sex]
        exact = [p for p in candidates if low <= _age(p.birth_date, today) <= high]
        patient = (exact or candidates or [p for p in pool if p.id not in used])[0]
        if not exact:
            # Synthetic demo: align age/sex with the procedure (deterministic).
            mid = (low + high) // 2
            patient.birth_date = date(today.year - mid, 6, 15)
            patient.sex = spec.sex
        used.add(patient.id)
        chosen[spec.case_code] = patient
    return chosen


def _evaluation_dicts(results: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in results:
        out.append(
            {
                "criterion_id": item.criterion_id,
                "criterion": item.criterion,
                "status": item.status,
                "reason": item.reason,
                "confidence": None,
                "evidence": [
                    {
                        "document_id": ref.document_id,
                        "chunk_id": ref.chunk_id,
                        "source": ref.source,
                        "text_reference": ref.text_reference,
                    }
                    for ref in item.evidence
                ],
            }
        )
    return out


def apply_india_checklists(session: Session) -> int:
    """Turn catalog filler policies POL-000002..8 into illustrative India checklists."""
    from app.services.indexing import index_document

    updated = 0
    for spec in INDIA_CHECKLISTS:
        policy = session.scalar(
            select(InsurancePolicy).where(InsurancePolicy.policy_code == spec.policy_code)
        )
        if policy is None:
            continue
        policy.title = spec.title
        policy.payer_name = PAYER_LABEL
        policy.procedure_name = spec.procedure
        policy.version = "india-illustrative-2026"
        policy.content = _policy_content(spec)
        document = session.get(Document, policy.document_id)
        if document is not None:
            document.content = policy.content
            meta = dict(document.document_metadata or {})
            meta.update({"checklist": spec.key, "market": "india", "illustrative": True})
            document.document_metadata = meta
            session.flush()
            index_document(session, document)
        session.execute(delete(PolicyCriterion).where(PolicyCriterion.policy_id == policy.id))
        for position, item in enumerate(spec.criteria, start=1):
            session.add(
                PolicyCriterion(
                    id=str(uuid4()),
                    criterion_code=str(item["code"]),
                    policy_id=policy.id,
                    description=str(item["description"]),
                    summary=str(item["description"]),
                    position=position,
                    rule=dict(item["rule"]),
                )
            )
        updated += 1
    session.flush()
    return updated


def seed_tpa_desk_demo(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Deterministic India TPA desk demo on top of the synthetic seed (synthetic mode only)."""
    from app.core.config import get_settings

    if get_settings().real_data_mode():
        return {"checklists": 0, "desk_cases": 0}
    current = now or datetime.now(UTC)
    checklists = apply_india_checklists(session)
    specs = demo_case_specs(current)
    cases = {
        case.case_code: case
        for case in session.scalars(
            select(AuthorizationCase).where(
                AuthorizationCase.case_code.in_([spec.case_code for spec in specs])
            )
        ).all()
    }
    policies = {
        policy.policy_code: policy
        for policy in session.scalars(select(InsurancePolicy)).all()
    }
    if len(cases) != len(specs) or any(spec.policy_code not in policies for spec in specs):
        logger.info("tpa_desk_demo_skipped reason=catalog_rows_missing")
        return {"checklists": checklists, "desk_cases": 0}
    from app.services.organizations import ensure_default_organization

    primary = ensure_default_organization(session)
    patients = _pick_patients(session, specs, org_id=primary.id, today=current.date())
    documents: list[Document] = []
    for number, spec in enumerate(specs, start=1):
        documents.extend(
            _apply_case(session, spec, cases[spec.case_code], patients[spec.case_code],
                        policies[spec.policy_code], number=number, now=current)
        )
    session.flush()
    from app.services.indexing import index_document

    for document in documents:
        index_document(session, document)
    session.flush()
    _seed_reviews_and_queries(session, specs, cases, patients, policies, now=current)
    session.flush()
    logger.info("tpa_desk_demo_seeded cases=%s checklists=%s", len(specs), checklists)
    return {"checklists": checklists, "desk_cases": len(specs)}


def _at(now: datetime, offset_h: float | None) -> datetime | None:
    return None if offset_h is None else now + timedelta(hours=offset_h)


def _apply_case(
    session: Session,
    spec: CaseSpec,
    case: AuthorizationCase,
    patient: Patient,
    policy: InsurancePolicy,
    *,
    number: int,
    now: datetime,
) -> list[Document]:
    patient.synthetic_name = f"{spec.name} (synthetic)"
    conditions = [str(item) for item in (patient.conditions or [])]
    patient.conditions = [*spec.conditions, *[c for c in conditions if c not in spec.conditions]]
    patient.updated_at = now

    created = _at(now, spec.prep_h) or now
    case.patient_id = patient.id
    case.policy_id = policy.id
    case.org_id = patient.org_id or case.org_id
    case.procedure = spec.treatment[:200]
    case.created_at = created
    case.updated_at = now
    case.prep_started_at = created
    case.payer_type = spec.payer_type
    case.insurer_name = spec.insurer
    case.tpa_name = spec.tpa
    case.policy_number = spec.policy_number
    case.admission_type = spec.admission_type
    case.admitted_at = _at(now, spec.admitted_h)
    case.expected_discharge_at = _at(now, spec.expected_discharge_h)
    case.treating_doctor = spec.doctor
    case.provisional_diagnosis = spec.diagnosis
    case.icd10_code = spec.icd10
    case.proposed_treatment = spec.treatment
    case.estimated_cost_inr = spec.estimate
    case.cost_breakdown_inr = dict(spec.costs)
    case.form_extra = dict(spec.form_extra)
    case.stage = spec.stage
    case.sent_at = _at(now, spec.sent_h)
    case.approved_amount_inr = spec.approved_amount
    case.approved_at = _at(now, spec.approved_h)
    case.revised_estimate_inr = spec.revised_estimate
    case.enhancement_reason = spec.enhancement_reason
    case.enhancement_requested_at = _at(now, spec.enhancement_h)
    case.enhancement_count = 1 if spec.enhancement_h is not None else 0
    case.discharge_requested_at = _at(now, spec.discharge_h)
    case.final_due_at = (
        _at(now, spec.discharge_h + 3) if spec.discharge_h is not None else None
    )
    case.closed_at = _at(now, spec.closed_h)
    case.decision_due_at = None
    if spec.stage == "sent" and case.sent_at is not None:
        case.decision_due_at = case.sent_at + timedelta(hours=1)
    if spec.stage == "enhancement" and case.enhancement_requested_at is not None:
        case.decision_due_at = case.enhancement_requested_at + timedelta(hours=1)
    review_at = _at(now, spec.review_h)
    if spec.review == "acknowledged":
        case.status = "closed_as_draft"
        case.review_ready_at = review_at
        case.lifecycle_note = "Senior confirmed the checklist (synthetic demo)"
    elif spec.review == "awaiting_senior":
        case.status = "ready_for_human"
        case.review_ready_at = review_at
        case.lifecycle_note = "Awaiting senior confirmation"
    else:
        case.status = "queued"

    added: list[Document] = []
    for index, doc in enumerate(spec.docs, start=1):
        stamp = now + timedelta(hours=doc.offset_h)
        code = f"TPA{number:02d}{index:02d}"
        document = Document(
            id=str(uuid4()),
            document_code=f"DOC-{code}",
            patient_id=patient.id,
            document_type=doc.document_type,
            source="tpa_desk_demo",
            content=doc.content,
            document_metadata={
                "dataset": "tpa_desk_demo (synthetic)",
                "case_id": spec.case_code,
                "specialty": spec.doctor.split("(")[-1].rstrip(")") if "(" in spec.doctor else "",
                **doc.metadata,
            },
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(document)
        session.flush()  # parent row first (PostgreSQL enforces the FK)
        added.append(document)
        if doc.as_note:
            session.add(
                ClinicalNote(
                    id=str(uuid4()),
                    note_code=f"NOTE-{code}",
                    patient_id=patient.id,
                    document_id=document.id,
                    note_type=doc.document_type,
                    content=doc.content,
                    authored_at=stamp,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
    for index, (test, value, unit) in enumerate(spec.labs, start=1):
        stamp = now + timedelta(hours=(spec.admitted_h if spec.admitted_h < 0 else -2) + 0.5)
        code = f"TPA{number:02d}L{index}"
        document = Document(
            id=str(uuid4()),
            document_code=f"DOC-{code}",
            patient_id=patient.id,
            document_type="lab_result",
            source="tpa_desk_demo",
            content=f"{test}: {value} {unit}".strip(),
            document_metadata={"dataset": "tpa_desk_demo (synthetic)", "specialty": "Laboratory"},
            created_at=stamp,
            updated_at=stamp,
        )
        session.add(document)
        session.flush()
        added.append(document)
        session.add(
            LabResult(
                id=str(uuid4()),
                lab_code=f"LAB-{code}",
                patient_id=patient.id,
                document_id=document.id,
                test_name=test,
                value=value,
                unit=unit,
                collected_at=stamp,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    for index, (modality, body_part, description) in enumerate(spec.imaging, start=1):
        stamp = now + timedelta(hours=spec.admitted_h + 1)
        session.add(
            ImagingStudy(
                id=str(uuid4()),
                imaging_code=f"IMG-TPA{number:02d}{index}",
                patient_id=patient.id,
                modality=modality,
                body_part=body_part,
                studied_at=stamp,
                description=description,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    for index, name in enumerate(spec.procedures, start=1):
        stamp = now + timedelta(hours=spec.admitted_h + 6)
        session.add(
            Procedure(
                id=str(uuid4()),
                procedure_code=f"PROC-TPA{number:02d}{index}",
                patient_id=patient.id,
                name=name[:200],
                performed_at=stamp,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    return added


def _seed_reviews_and_queries(
    session: Session,
    specs: tuple[CaseSpec, ...],
    cases: dict[str, AuthorizationCase],
    patients: dict[str, Patient],
    policies: dict[str, InsurancePolicy],
    *,
    now: datetime,
) -> None:
    from app.db.repository import next_public_code
    from app.services.case_checklist import live_rule_results

    for number, spec in enumerate(specs, start=1):
        case = cases[spec.case_code]
        patient = patients[spec.case_code]
        policy = policies[spec.policy_code]
        prep_at = _at(now, spec.prep_h) or now
        session.add(
            AuditEvent(
                id=str(uuid4()),
                action="evidence_pack_prepare",
                actor=DESK_ACTOR,
                resource_type="authorization_case",
                resource_id=spec.case_code,
                status="completed",
                detail=f"patient={patient.patient_code};seed=tpa_desk_demo",
                created_at=prep_at + timedelta(minutes=2),
                updated_at=prep_at + timedelta(minutes=2),
            )
        )
        if spec.review in {"acknowledged", "awaiting_senior"}:
            results = _evaluation_dicts(live_rule_results(session, patient, policy))
            run_id = f"seed-tpa-{number:02d}"
            acknowledged = spec.review == "acknowledged"
            missing = [row["criterion"] for row in results if row["status"] == "MISSING"]
            state: dict[str, Any] = {
                "run_id": run_id,
                "trace_id": f"seed-trace-tpa-{number:02d}",
                "patient_id": patient.patient_code,
                "policy_id": policy.policy_code,
                "procedure": spec.treatment,
                "case_id": spec.case_code,
                "criterion_results": results,
                "evidence": [],
                "citations": [ref for row in results for ref in row["evidence"]],
                "missing_evidence": missing,
                "contradictions": [],
                "evidence_coverage": "AVAILABLE" if results else "NONE",
                "human_review_required": True,
                "human_review_reason": (
                    "Senior confirmation of the checklist required; reviewer=Citations checked "
                    "against the chart (synthetic demo)"
                    if acknowledged
                    else "Senior confirmation of the checklist required"
                ),
                "human_decision": "acknowledged" if acknowledged else None,
                "paused": not acknowledged,
                "status": "completed" if acknowledged else "awaiting_human_review",
                "scoring_path": "rules",
                "report_summary": "Synthetic desk demo — checklist scored by rule check.",
                "agent_trace": [],
                "errors": [],
                "retrieve_pass": 1,
                "max_retrieve_passes": 2,
                "need_imaging": False,
            }
            stamp = _at(now, spec.review_h) or now
            session.add(ReviewRun(run_id=run_id, state_json=state, updated_at=stamp))
            case.last_run_id = run_id
            if acknowledged:
                session.add(
                    AuditEvent(
                        id=str(uuid4()),
                        action="evidence_pack_review",
                        actor=SENIOR_ACTOR,
                        resource_type="authorization_case",
                        resource_id=spec.case_code,
                        status="completed",
                        detail=f"reason=confirm;decision=acknowledged;run={run_id}",
                        created_at=stamp,
                        updated_at=stamp,
                    )
                )
        for query in spec.queries:
            raised = now + timedelta(hours=query.raised_h)
            responded = _at(now, query.responded_h)
            session.add(
                CaseQuery(
                    id=str(uuid4()),
                    query_code=next_public_code(session, CaseQuery.query_code, "Q"),
                    case_id=case.id,
                    raised_at=raised,
                    text=query.text,
                    response_due_at=raised + timedelta(hours=query.due_hours),
                    responded_at=responded,
                    response=query.response,
                    raised_by=case.tpa_name or case.insurer_name,
                    responded_by=DESK_ACTOR if responded else "",
                    resume_stage=query.resume_stage,
                    created_at=raised,
                    updated_at=responded or raised,
                )
            )
            session.flush()
