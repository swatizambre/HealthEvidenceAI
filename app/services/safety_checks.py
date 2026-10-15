"""Cross-hospital safety checks on a patient's own record.

Three deterministic checks run over every record the patient holds, whichever
hospital or clinic it came from:

* allergy conflict: a recorded allergy and an active medicine from the same
  drug or drug family;
* same medicine twice: two active medicines that resolve to the same generic;
* test not repeated: the latest result of a tracked test is out of range and no
  newer result exists after the follow-up window.

Findings are framed as questions for the patient and as source-linked review
items for the doctor. Nothing here diagnoses, prescribes or tells anyone to stop
a medicine. The drug maps are small and explicit; they are not a formulary or a
full interaction checker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import LabResult, Medication, Patient
from app.services.records import require_patient

FOLLOW_UP_DAYS = 90

_INACTIVE_STATUSES = frozenset({"stopped", "completed", "inactive", "discontinued", "cancelled"})

# Brand → generic for common Indian brands (extends doctor_view's demo map).
_BRAND_TO_GENERIC: dict[str, str] = {
    "crocin": "paracetamol",
    "dolo": "paracetamol",
    "calpol": "paracetamol",
    "augmentin": "amoxicillin-clavulanate",
    "clavam": "amoxicillin-clavulanate",
    "moxikind": "amoxicillin",
    "mox": "amoxicillin",
    "novamox": "amoxicillin",
    "azithral": "azithromycin",
    "pantocid": "pantoprazole",
    "pan": "pantoprazole",
    "ecosprin": "aspirin",
    "disprin": "aspirin",
    "brufen": "ibuprofen",
    "combiflam": "ibuprofen-paracetamol",
    "voveran": "diclofenac",
    "zerodol": "aceclofenac",
    "clopilet": "clopidogrel",
    "glycomet": "metformin",
    "glucophage": "metformin",
    "gluconorm": "metformin",
    "telma": "telmisartan",
    "amlong": "amlodipine",
    "atorva": "atorvastatin",
    "rosuvas": "rosuvastatin",
    "thyronorm": "levothyroxine",
    "eltroxin": "levothyroxine",
    "septran": "sulfamethoxazole-trimethoprim",
    "bactrim": "sulfamethoxazole-trimethoprim",
    "taxim": "cefixime",
    "zifi": "cefixime",
    "monocef": "ceftriaxone",
}

# Drug families used for allergy matching. A drug named in an allergy also
# flags the rest of its family, because cross-reactivity is the question.
_DRUG_FAMILIES: dict[str, frozenset[str]] = {
    "penicillin": frozenset(
        {"penicillin", "amoxicillin", "ampicillin", "cloxacillin", "piperacillin", "flucloxacillin"}
    ),
    "cephalosporin": frozenset({"cefixime", "ceftriaxone", "cefuroxime", "cephalexin", "cefpodoxime"}),
    "sulfonamide": frozenset({"sulfamethoxazole", "sulfasalazine", "cotrimoxazole"}),
    "nsaid": frozenset({"ibuprofen", "diclofenac", "naproxen", "aspirin", "aceclofenac", "mefenamic"}),
}

_FAMILY_WORDS: dict[str, tuple[str, ...]] = {
    "penicillin": ("penicillin",),
    "cephalosporin": ("cephalosporin",),
    "sulfonamide": ("sulfa", "sulpha", "sulfonamide", "sulphonamide"),
    "nsaid": ("nsaid", "painkiller"),
}

_ALLERGY_WORDS = ("allerg", "hypersens", "anaphyla", "adverse reaction")


@dataclass(frozen=True)
class _LabRule:
    key: str
    label: str
    match: tuple[str, ...]
    exclude: tuple[str, ...]
    low: float | None
    high: float | None


# Tracked tests and the values outside which a repeat test is usually expected.
_LAB_RULES: tuple[_LabRule, ...] = (
    _LabRule("hba1c", "HbA1c", ("a1c", "hba1c", "glycated"), (), None, 6.5),
    _LabRule("ldl", "LDL cholesterol", ("ldl", "low density lipoprotein"), (), None, 160.0),
    _LabRule("creatinine", "Creatinine", ("creatinine",), ("clearance", "urine"), None, 1.3),
    _LabRule("potassium", "Potassium", ("potassium",), ("urine",), 3.5, 5.5),
    _LabRule(
        "hemoglobin", "Haemoglobin", ("hemoglobin", "haemoglobin"), ("a1c", "glycated", "urine"), 10.0, None
    ),
    _LabRule("tsh", "TSH", ("tsh", "thyrotropin", "thyroid stimulating"), (), 0.4, 4.5),
)

_TEXT_ABNORMAL = frozenset({"high", "low", "critical", "abnormal", "positive", "h", "l"})

DISCLAIMER = (
    "These checks compare records from every place the patient was seen. They are questions "
    "for the doctor, not advice: do not start or stop a medicine because of them. Drug "
    "matching uses a small built-in list, not a full interaction checker."
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def generic_name(medicine: str) -> str:
    """Resolve a brand or product label to a generic key (first known word wins)."""
    words = _tokens(medicine)
    for word in words:
        if word in _BRAND_TO_GENERIC:
            return _BRAND_TO_GENERIC[word]
    known = {member for family in _DRUG_FAMILIES.values() for member in family}
    known.update(_BRAND_TO_GENERIC.values())
    ingredients = [word for word in words if word in known]
    if ingredients:
        return "-".join(dict.fromkeys(ingredients))
    return words[0] if words else ""


def _ingredients(generic: str) -> set[str]:
    return {part for part in generic.split("-") if part}


def _family_of(drug: str) -> str | None:
    for family, members in _DRUG_FAMILIES.items():
        if drug in members:
            return family
    return None


def _allergy_targets(text: str) -> dict[str, str]:
    """Map drug → why it matches, for one allergy statement."""
    lower = text.lower()
    words = set(_tokens(text))
    targets: dict[str, str] = {}
    for family, cues in _FAMILY_WORDS.items():
        if any(cue in lower for cue in cues):
            for drug in _DRUG_FAMILIES[family]:
                targets.setdefault(drug, f"{family} family")
    for word in words:
        generic = _BRAND_TO_GENERIC.get(word, word)
        for drug in _ingredients(generic):
            family = _family_of(drug)
            if family is None:
                if drug in _BRAND_TO_GENERIC.values():
                    targets[drug] = "same medicine"
                continue
            targets[drug] = "same medicine"
            for member in _DRUG_FAMILIES[family]:
                targets.setdefault(member, f"same family ({family})")
    return targets


def _is_active(med: Medication) -> bool:
    return (med.status or "").strip().lower() not in _INACTIVE_STATUSES


def _parse_number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(match.group()) if match else None


def _lab_rule(test_name: str) -> _LabRule | None:
    lower = (test_name or "").lower()
    for rule in _LAB_RULES:
        if any(cue in lower for cue in rule.match) and not any(cue in lower for cue in rule.exclude):
            return rule
    return None


def _out_of_range(rule: _LabRule, value: str) -> str | None:
    text = (value or "").strip().lower()
    if text in _TEXT_ABNORMAL:
        return "high" if text in {"high", "h", "critical", "positive", "abnormal"} else "low"
    number = _parse_number(value)
    if number is None:
        return None
    if rule.high is not None and number >= rule.high:
        return "high"
    if rule.low is not None and number < rule.low:
        return "low"
    return None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _day(value: datetime) -> str:
    return _as_utc(value).date().isoformat()


def _source_med(med: Medication) -> dict[str, str]:
    return {
        "ref": f"medication:{med.medication_code}",
        "label": f"{med.name} {med.dose}".strip() + f", started {_day(med.started_at)}",
    }


def _source_lab(lab: LabResult) -> dict[str, str]:
    return {
        "ref": f"lab:{lab.lab_code}",
        "label": f"{lab.test_name}: {lab.value} {lab.unit}".strip() + f", {_day(lab.collected_at)}",
    }


def _allergy_findings(patient: Patient, meds: list[Medication]) -> list[dict[str, Any]]:
    allergies = [
        str(item)
        for item in (patient.conditions or [])
        if any(word in str(item).lower() for word in _ALLERGY_WORDS)
    ]
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, allergy in enumerate(allergies):
        targets = _allergy_targets(allergy)
        if not targets:
            continue
        for med in meds:
            hits = sorted(_ingredients(generic_name(med.name)) & set(targets))
            if not hits:
                continue
            key = (allergy, med.medication_code)
            if key in seen:
                continue
            seen.add(key)
            drug = hits[0]
            why = targets[drug]
            findings.append(
                {
                    "id": f"allergy-{med.medication_code}-{index}",
                    "kind": "allergy_conflict",
                    "severity": "high",
                    "title": f"Allergy on record and an active medicine containing {drug}",
                    "patient_text": (
                        f'Your record says: "{allergy}". You also have {med.name} on your medicine '
                        f"list ({why}). Please ask the doctor who prescribed it before your next dose."
                    ),
                    "doctor_text": (
                        f'Recorded allergy "{allergy}"; active {med.name} {med.dose} contains {drug} ({why}).'
                    ),
                    "sources": [
                        {"ref": f"condition:{index}", "label": allergy},
                        _source_med(med),
                    ],
                }
            )
    return findings


def _duplicate_findings(meds: list[Medication]) -> list[dict[str, Any]]:
    groups: dict[str, list[Medication]] = {}
    for med in meds:
        generic = generic_name(med.name)
        if generic:
            groups.setdefault(generic, []).append(med)
    findings: list[dict[str, Any]] = []
    for generic, group in sorted(groups.items()):
        names = {med.name.strip().lower() for med in group}
        if len(group) < 2:
            continue
        same_label = len(names) == 1
        findings.append(
            {
                "id": f"duplicate-{generic}",
                "kind": "duplicate_medicine",
                "severity": "review",
                "title": f"{generic.replace('-', ' + ').capitalize()} appears {len(group)} times",
                "patient_text": (
                    f"{len(group)} active prescriptions contain {generic.replace('-', ' + ')}"
                    + ("" if same_label else ", under different names")
                    + ". Ask your doctor whether you should take all of them. "
                    "Don't stop any medicine on your own."
                ),
                "doctor_text": (
                    f"{len(group)} active entries resolve to {generic}: "
                    + "; ".join(f"{med.name} {med.dose}".strip() for med in group)
                    + "."
                ),
                "sources": [_source_med(med) for med in group],
            }
        )
    return findings


def _follow_up_findings(labs: list[LabResult], now: datetime) -> list[dict[str, Any]]:
    latest: dict[str, tuple[_LabRule, LabResult]] = {}
    for lab in labs:
        rule = _lab_rule(lab.test_name)
        if rule is None:
            continue
        current = latest.get(rule.key)
        if current is None or _as_utc(lab.collected_at) > _as_utc(current[1].collected_at):
            latest[rule.key] = (rule, lab)
    findings: list[dict[str, Any]] = []
    cutoff = now - timedelta(days=FOLLOW_UP_DAYS)
    for key, (rule, lab) in sorted(latest.items()):
        direction = _out_of_range(rule, lab.value)
        if direction is None or _as_utc(lab.collected_at) > cutoff:
            continue
        days = (now - _as_utc(lab.collected_at)).days
        findings.append(
            {
                "id": f"followup-{key}",
                "kind": "test_not_repeated",
                "severity": "review",
                "title": f"{rule.label} was {direction} and has not been repeated",
                "patient_text": (
                    f"Your {rule.label} was {lab.value} {lab.unit}".strip()
                    + f" on {_day(lab.collected_at)} and there is no newer result. "
                    "Ask your doctor whether it should be repeated."
                ),
                "doctor_text": (
                    f"Latest {rule.label} {lab.value} {lab.unit}".strip()
                    + f" ({direction}) on {_day(lab.collected_at)}, {days} days ago; no later result on file."
                ),
                "sources": [_source_lab(lab)],
            }
        )
    return findings


_SEVERITY_ORDER = {"high": 0, "review": 1}


def run_safety_checks(session: Session, patient_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Run all checks for one patient and return findings, most severe first."""
    patient = require_patient(session, patient_id)
    current = _as_utc(now or datetime.now(UTC))
    meds = [
        med
        for med in session.scalars(
            select(Medication).where(Medication.patient_id == patient.id).order_by(Medication.started_at)
        ).all()
        if _is_active(med)
    ]
    labs = list(session.scalars(select(LabResult).where(LabResult.patient_id == patient.id)).all())
    allergy_count = sum(
        1 for item in (patient.conditions or []) if any(word in str(item).lower() for word in _ALLERGY_WORDS)
    )
    findings = [
        *_allergy_findings(patient, meds),
        *_duplicate_findings(meds),
        *_follow_up_findings(labs, current),
    ]
    findings.sort(key=lambda item: (_SEVERITY_ORDER.get(item["severity"], 9), item["id"]))
    return {
        "patient_id": patient.patient_code,
        "checked_at": current.isoformat(),
        "checked": {
            "active_medicines": len(meds),
            "lab_results": len(labs),
            "allergies": allergy_count,
        },
        "findings": findings,
        "disclaimer": DISCLAIMER,
    }
