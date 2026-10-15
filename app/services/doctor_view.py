"""Doctor chart brief, risk flags, and medicine reconciliation (demo scaffolding)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import LabResult, Medication, Procedure
from app.services.lifelong import get_lifelong_summary
from app.services.records import get_patient_essentials, require_patient

# Small demo brand → generic map (India common brands). Not a formulary.
_BRAND_TO_GENERIC: dict[str, str] = {
    "crocin": "paracetamol",
    "dolo": "paracetamol",
    "calpol": "paracetamol",
    "augmentin": "amoxicillin-clavulanate",
    "azithral": "azithromycin",
    "pantocid": "pantoprazole",
    "pan": "pantoprazole",
    "ecosprin": "aspirin",
    "clopilet": "clopidogrel",
    "metformin": "metformin",
    "glycomet": "metformin",
    "telma": "telmisartan",
    "amlodipine": "amlodipine",
    "atorva": "atorvastatin",
    "rosuvas": "rosuvastatin",
    "thyronorm": "levothyroxine",
    "insulin": "insulin",
}


def _normalize_med_name(name: str) -> str:
    raw = re.sub(r"[^a-z0-9\s\-]", "", (name or "").lower()).strip()
    token = raw.split()[0] if raw else ""
    return _BRAND_TO_GENERIC.get(token, token or raw)


def medicine_reconciliation(session: Session, patient_id: str) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    meds = list(
        session.scalars(
            select(Medication).where(Medication.patient_id == patient.id).order_by(Medication.name)
        ).all()
    )
    items: list[dict[str, Any]] = []
    by_generic: dict[str, list[str]] = {}
    for med in meds:
        generic = _normalize_med_name(med.name)
        items.append(
            {
                "name": med.name,
                "dose": med.dose,
                "status": med.status,
                "generic_key": generic,
            }
        )
        by_generic.setdefault(generic, []).append(med.name)
    duplicates = [
        {"generic_key": key, "names": names}
        for key, names in by_generic.items()
        if key and len(names) > 1
    ]
    return {
        "medications": items,
        "duplicate_groups": duplicates,
        "disclaimer": (
            "Brand→generic matching is a small heuristic map for demo continuity — "
            "not a drug-interaction or formulary check."
        ),
    }


def risk_flags(session: Session, patient_id: str) -> list[dict[str, str]]:
    patient = require_patient(session, patient_id)
    flags: list[dict[str, str]] = []
    for condition in patient.conditions or []:
        lower = str(condition).lower()
        if "allerg" in lower or "hypersens" in lower or "anaphyla" in lower:
            flags.append(
                {
                    "kind": "allergy",
                    "label": str(condition),
                    "source": "patient.conditions",
                }
            )
    procedures = session.scalars(
        select(Procedure).where(Procedure.patient_id == patient.id)
    ).all()
    for proc in procedures:
        name = (proc.name or "").lower()
        if any(token in name for token in ("implant", "stent", "pacemaker", "prosthes", "mesh")):
            flags.append(
                {
                    "kind": "implant",
                    "label": proc.name,
                    "source": f"procedure:{proc.procedure_code}",
                }
            )
    labs = session.scalars(
        select(LabResult)
        .where(LabResult.patient_id == patient.id)
        .order_by(LabResult.collected_at.desc())
    ).all()
    for lab in labs[:40]:
        value = (lab.value or "").strip().lower()
        if value in {"high", "low", "critical", "abnormal"} or value.startswith(">"):
            flags.append(
                {
                    "kind": "lab_followup",
                    "label": f"{lab.test_name}: {lab.value} {lab.unit}".strip(),
                    "source": f"lab:{lab.lab_code}",
                }
            )
    return flags[:25]


def doctor_brief_pack(session: Session, patient_id: str) -> dict[str, Any]:
    patient = require_patient(session, patient_id)
    essentials = get_patient_essentials(session, patient_id)
    lifelong = get_lifelong_summary(session, patient_id)
    meds = medicine_reconciliation(session, patient_id)
    flags = risk_flags(session, patient_id)
    brief_lines = [
        {
            "text": essentials.doctor_brief,
            "source": "essentials.doctor_brief",
        }
    ]
    if lifelong.doctor_brief:
        brief_lines.append({"text": lifelong.doctor_brief, "source": "lifelong.doctor_brief"})
    for flag in flags[:5]:
        brief_lines.append(
            {
                "text": f"Risk flag ({flag['kind']}): {flag['label']}",
                "source": flag["source"],
            }
        )
    return {
        "patient_id": patient.patient_code,
        "display_name": patient.synthetic_name,
        "brief_lines": brief_lines[:12],
        "risk_flags": flags,
        "medications": meds,
        "completeness_percent": essentials.completeness_percent,
        "disclaimer": (
            "Organises chart facts with sources for clinician review. "
            "Does not diagnose, prescribe, or decide coverage."
        ),
    }


def ask_chart_with_sources(
    session: Session, patient_id: str, question: str
) -> dict[str, Any]:
    """Deterministic chart Q&A with citations — optional LLM phrasing is out of scope here."""
    patient = require_patient(session, patient_id)
    q = (question or "").strip().lower()
    hits: list[dict[str, str]] = []
    if any(token in q for token in ("allerg", "contrast", "reaction", "anaphyla")):
        for condition in patient.conditions or []:
            if any(
                token in str(condition).lower()
                for token in ("allerg", "contrast", "hypersens", "anaphyla", "reaction")
            ):
                hits.append({"text": str(condition), "source": "patient.conditions"})
        if not hits:
            hits.append(
                {
                    "text": "No allergy or contrast-reaction wording found on the structured chart.",
                    "source": "not_found",
                }
            )
    elif any(token in q for token in ("implant", "stent", "pacemaker", "device")):
        for flag in risk_flags(session, patient_id):
            if flag["kind"] == "implant":
                hits.append({"text": flag["label"], "source": flag["source"]})
        if not hits:
            hits.append({"text": "No implant-like procedures found.", "source": "not_found"})
    elif any(token in q for token in ("medicine", "medication", "drug", "tablet")):
        meds = medicine_reconciliation(session, patient_id)["medications"]
        for med in meds[:10]:
            hits.append(
                {
                    "text": f"{med['name']} ({med['dose']}) — {med['status']}",
                    "source": f"medication:{med['generic_key']}",
                }
            )
        if not hits:
            hits.append({"text": "No medications on file.", "source": "not_found"})
    else:
        essentials = get_patient_essentials(session, patient_id)
        hits.append({"text": essentials.doctor_brief, "source": "essentials.doctor_brief"})
        for action in essentials.next_actions[:3]:
            hits.append({"text": action, "source": "essentials.next_actions"})
    return {
        "patient_id": patient.patient_code,
        "question": question,
        "answers": hits,
        "disclaimer": (
            "Answers are limited to stored chart text. Not found means not in this chart — "
            "not a clinical negative finding."
        ),
    }
