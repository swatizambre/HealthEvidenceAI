"""Hospital multi-specialty catalog for OPD and patient-file filtering.

Maps free-text department labels to a stable specialty used in the digital chart.
Covers common hospital service lines across medicine and surgery — tagging and
routing only, not specialty-specific clinical pathways.
"""

from __future__ import annotations

SPECIALTY_CATALOG: tuple[str, ...] = (
    # Primary / hospital medicine
    "General medicine",
    "Family medicine",
    "Geriatrics",
    "Emergency medicine",
    "Critical care",
    # Medical specialties
    "Cardiology",
    "Endocrinology",
    "Pulmonology",
    "Gastroenterology",
    "Nephrology",
    "Neurology",
    "Oncology",
    "Hematology",
    "Rheumatology",
    "Infectious disease",
    "Allergy & immunology",
    "Dermatology",
    "Psychiatry",
    # Women's / child health
    "Obstetrics & gynecology",
    "Pediatrics",
    "Neonatology",
    # Surgical / procedural
    "Surgery",
    "Orthopedics",
    "Neurosurgery",
    "Cardiac surgery",
    "Vascular surgery",
    "Plastic surgery",
    "Urology",
    "ENT",
    "Ophthalmology",
    "Dentistry & oral surgery",
    "Anesthesiology",
    "Pain medicine",
    "Physical medicine & rehabilitation",
    "Physiotherapy",
    # Diagnostics / support
    "Radiology",
    "Pathology",
    "Laboratory",
    "Pharmacy",
    "Nuclear medicine",
)

_SUPPORT_SPECIALTIES = frozenset(
    {"Laboratory", "Pharmacy", "Radiology", "Pathology", "Nuclear medicine", "Anesthesiology"}
)

_ALIASES: dict[str, str] = {
    # General / primary
    "opd": "General medicine",
    "general opd": "General medicine",
    "general medicine": "General medicine",
    "internal medicine": "General medicine",
    "medicine": "General medicine",
    "family medicine": "Family medicine",
    "family practice": "Family medicine",
    "gp": "Family medicine",
    "geriatrics": "Geriatrics",
    "geriatric medicine": "Geriatrics",
    "critical care": "Critical care",
    "icu": "Critical care",
    "intensive care": "Critical care",
    # Cardio / pulm / endo
    "cardio": "Cardiology",
    "cardiology": "Cardiology",
    "heart": "Cardiology",
    "endo": "Endocrinology",
    "endocrinology": "Endocrinology",
    "diabetes": "Endocrinology",
    "pulmonary": "Pulmonology",
    "pulmonology": "Pulmonology",
    "respiratory": "Pulmonology",
    "chest": "Pulmonology",
    # GI / renal / neuro
    "gastro": "Gastroenterology",
    "gastroenterology": "Gastroenterology",
    "gi": "Gastroenterology",
    "nephro": "Nephrology",
    "nephrology": "Nephrology",
    "renal": "Nephrology",
    "neuro": "Neurology",
    "neurology": "Neurology",
    # Oncology / heme / rheum / ID
    "oncology": "Oncology",
    "cancer": "Oncology",
    "medical oncology": "Oncology",
    "hematology": "Hematology",
    "haematology": "Hematology",
    "heme": "Hematology",
    "rheumatology": "Rheumatology",
    "rheum": "Rheumatology",
    "infectious disease": "Infectious disease",
    "infectious diseases": "Infectious disease",
    "id": "Infectious disease",
    "allergy": "Allergy & immunology",
    "immunology": "Allergy & immunology",
    "allergy & immunology": "Allergy & immunology",
    "dermatology": "Dermatology",
    "derm": "Dermatology",
    "psychiatry": "Psychiatry",
    "mental health": "Psychiatry",
    # Women's / child
    "obgyn": "Obstetrics & gynecology",
    "ob/gyn": "Obstetrics & gynecology",
    "ob gyn": "Obstetrics & gynecology",
    "obstetrics": "Obstetrics & gynecology",
    "gynecology": "Obstetrics & gynecology",
    "gynaecology": "Obstetrics & gynecology",
    "maternity": "Obstetrics & gynecology",
    "pediatrics": "Pediatrics",
    "paediatrics": "Pediatrics",
    "neonatology": "Neonatology",
    "nicu": "Neonatology",
    # Surgical
    "surgery": "Surgery",
    "general surgery": "Surgery",
    "ortho": "Orthopedics",
    "orthopedics": "Orthopedics",
    "orthopaedics": "Orthopedics",
    "neurosurgery": "Neurosurgery",
    "brain surgery": "Neurosurgery",
    "cardiac surgery": "Cardiac surgery",
    "cardiothoracic": "Cardiac surgery",
    "cts": "Cardiac surgery",
    "vascular": "Vascular surgery",
    "vascular surgery": "Vascular surgery",
    "plastic surgery": "Plastic surgery",
    "plastics": "Plastic surgery",
    "urology": "Urology",
    "ent": "ENT",
    "otolaryngology": "ENT",
    "ear nose throat": "ENT",
    "ophthalmology": "Ophthalmology",
    "eye": "Ophthalmology",
    "dental": "Dentistry & oral surgery",
    "dentistry": "Dentistry & oral surgery",
    "oral surgery": "Dentistry & oral surgery",
    "maxillofacial": "Dentistry & oral surgery",
    "anesthesiology": "Anesthesiology",
    "anaesthesiology": "Anesthesiology",
    "anesthesia": "Anesthesiology",
    "pain": "Pain medicine",
    "pain medicine": "Pain medicine",
    "pain management": "Pain medicine",
    "pmr": "Physical medicine & rehabilitation",
    "physiatry": "Physical medicine & rehabilitation",
    "rehabilitation": "Physical medicine & rehabilitation",
    "physical medicine": "Physical medicine & rehabilitation",
    "physiotherapy": "Physiotherapy",
    "physio": "Physiotherapy",
    "physical therapy": "Physiotherapy",
    "pt": "Physiotherapy",
    # Emergency / diagnostics
    "emergency": "Emergency medicine",
    "er": "Emergency medicine",
    "casualty": "Emergency medicine",
    "a&e": "Emergency medicine",
    "radiology": "Radiology",
    "imaging": "Radiology",
    "pathology": "Pathology",
    "path": "Pathology",
    "lab": "Laboratory",
    "laboratory": "Laboratory",
    "pharmacy": "Pharmacy",
    "nuclear medicine": "Nuclear medicine",
    "nuclear": "Nuclear medicine",
}


def normalize_specialty(value: str | None, *, fallback: str = "General medicine") -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    key = " ".join(raw.lower().replace("&", "and").replace("/", " ").split())
    key = key.replace(" and ", " & ")
    if raw in SPECIALTY_CATALOG:
        return raw
    mapped = _ALIASES.get(key) or _ALIASES.get(raw.lower().strip())
    if mapped:
        return mapped
    # Prefer longer catalog matches so "cardiac surgery" is not swallowed by "Cardiology".
    for specialty in sorted(SPECIALTY_CATALOG, key=len, reverse=True):
        label = specialty.lower()
        if label in key or key in label:
            return specialty
    # Title-case unknown hospital departments so they remain filterable.
    return raw[:80]


def specialty_for_event_type(event_type: str, *, department: str | None = None) -> str:
    if department:
        return normalize_specialty(department)
    defaults = {
        "lab_result": "Laboratory",
        "imaging_study": "Radiology",
        "medication": "Pharmacy",
        "claim": "General medicine",
        "procedure": "Surgery",
        "clinical_note": "General medicine",
    }
    return defaults.get(event_type, "General medicine")


def clinical_specialty_catalog() -> tuple[str, ...]:
    """Service lines shown for clinical encounter tagging (excludes pure support labs)."""
    return tuple(item for item in SPECIALTY_CATALOG if item not in _SUPPORT_SPECIALTIES)


def seed_specialty_for_patient(patient_number: int) -> str:
    """Rotate specialties across seeded patients so demos look multi-specialty."""
    catalog = list(clinical_specialty_catalog())
    return catalog[(max(patient_number, 1) - 1) % len(catalog)]
