"""Disorder / condition labels for lifelong history filters.

Filter chapters are clinical problems (diabetes, thyroid, disc disease, …),
not specialty service lines, hospitals, or social findings.
"""

from __future__ import annotations

# Display labels used as filter chips (stable catalog).
DISORDER_CATALOG: tuple[str, ...] = (
    "Diabetes",
    "Thyroid disorder",
    "Hypertension",
    "Heart disease",
    "Asthma / COPD",
    "Disc disease / back pain",
    "Trauma / injury",
    "Obstetric history",
    "Gastritis / GI",
    "Kidney disease",
    "Cancer history",
    "Neurological disorder",
    "Arthritis / joint",
    "Infection",
    "Anemia",
    "Mental health",
    "Substance use",
    "Dental",
    "Other clinical",
)

# Longer / more specific needles first within each disorder.
_DISORDER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Diabetes",
        ("diabetes", "diabetic", "type 2 dm", "type 1 dm", "hyperglycemia", "hba1c"),
    ),
    (
        "Thyroid disorder",
        ("thyroid", "hypothyroid", "hyperthyroid", "hashimoto", "graves", "goiter"),
    ),
    (
        "Hypertension",
        ("hypertension", "hypertensive", "high blood pressure", "elevated bp"),
    ),
    (
        "Heart disease",
        ("heart failure", "coronary", "myocardial", "cabg", "angioplasty", "cardiac", "chf", "ischemic"),
    ),
    (
        "Asthma / COPD",
        ("asthma", "copd", "chronic obstructive", "emphysema", "bronchitis"),
    ),
    (
        "Disc disease / back pain",
        (
            "disc",
            "low back",
            "lumbar",
            "spine",
            "sciatica",
            "spondyl",
            "back pain",
            "lumbar stabilization",
        ),
    ),
    (
        "Trauma / injury",
        ("accident", "trauma", "fracture", "soft tissue", "injury", "sprain", "laceration"),
    ),
    (
        "Obstetric history",
        ("lscs", "cesarean", "caesarean", "c-section", "obstetric", "pregnancy", "postpartum", "delivery"),
    ),
    (
        "Gastritis / GI",
        ("gastritis", "gastric", "ulcer", "gerd", "reflux", "append", "bowel", "ibs", "gi bleed"),
    ),
    (
        "Kidney disease",
        ("kidney", "renal", "ckd", "nephropathy", "dialysis"),
    ),
    (
        "Cancer history",
        ("cancer", "carcinoma", "malignancy", "oncolog", "tumor", "chemotherapy"),
    ),
    (
        "Neurological disorder",
        ("stroke", "seizure", "epilepsy", "parkinson", "neuropathy", "migraine", "neurolog"),
    ),
    (
        "Arthritis / joint",
        ("arthritis", "osteoarthritis", "rheumatoid", "knee", "hip", "joint pain"),
    ),
    (
        "Infection",
        (
            "infection",
            "sepsis",
            "pneumonia",
            "uti",
            "tuberculosis",
            "covid",
            "sinusitis",
            "pharyngitis",
            "influenza",
            "septic",
        ),
    ),
    (
        "Anemia",
        ("anemia", "anaemia", "low hemoglobin", "iron deficiency"),
    ),
    (
        "Mental health",
        ("depression", "anxiety", "psychiatric", "bipolar", "mental health"),
    ),
    (
        "Substance use",
        ("overdose", "drug abuse", "substance", "alcohol dependence", "opioid", "addiction"),
    ),
    (
        "Dental",
        ("molar", "dental", "tooth", "teeth", "oral surgery", "impacted"),
    ),
)

# Map seeded / problem-list slugs onto catalog labels.
_CONDITION_ALIASES: dict[str, str] = {
    "diabetes": "Diabetes",
    "type_2_diabetes": "Diabetes",
    "type_1_diabetes": "Diabetes",
    "diabetes_mellitus": "Diabetes",
    "thyroid": "Thyroid disorder",
    "hypothyroidism": "Thyroid disorder",
    "hyperthyroidism": "Thyroid disorder",
    "hypertension": "Hypertension",
    "essential_hypertension": "Hypertension",
    "asthma": "Asthma / COPD",
    "copd": "Asthma / COPD",
    "heart_failure": "Heart disease",
    "coronary_artery_disease": "Heart disease",
    "ckd": "Kidney disease",
    "chronic_kidney_disease": "Kidney disease",
    "anemia": "Anemia",
    "depression": "Mental health",
    "anxiety": "Mental health",
    "osteoarthritis": "Arthritis / joint",
    "back_pain": "Disc disease / back pain",
    "lumbar_disc": "Disc disease / back pain",
    "migraine": "Neurological disorder",
    "overdose": "Substance use",
    "dependent_drug_abuse": "Substance use",
    "viral_sinusitis": "Infection",
    "acute_viral_pharyngitis": "Infection",
    "impacted_molars": "Dental",
}

# Synthea / SNOMED social & admin noise — never lifelong clinical chapters.
_NON_CLINICAL_MARKERS: tuple[str, ...] = (
    "(finding)",
    "(situation)",
    "(observable entity)",
    "education",
    "employment",
    "homeless",
    "social isolation",
    "received primary school",
    "full-time employment",
    "part-time employment",
    "unemployed",
    "medication review due",
    "medication reconciliation",
    "has a criminal record",
    "victim of intimate partner abuse",
    "transportation insecurity",
    "food insecurity",
    "housing",
    "unsatisfactory housing",
    "lack of access",
    "refugee",
    "immigrant",
    "lives alone",
    "stress (finding)",
    "received higher education",
    "limited social contact",
)


def is_clinical_condition(condition: str) -> bool:
    """Keep true clinical disorders; drop social findings and chart admin noise."""
    raw = (condition or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(marker in lower for marker in _NON_CLINICAL_MARKERS):
        return False
    # Prefer SNOMED-style "(disorder)" and catalog matches.
    if "(disorder)" in lower:
        return True
    if disorders_for_condition(raw):
        return True
    return False


def is_clinical_criterion_text(text: str) -> bool:
    """Keep checklist rows that are clinical; drop social/admin Synthea noise."""
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(marker in lower for marker in _NON_CLINICAL_MARKERS):
        return False
    return True


def normalize_disorder_label(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw in DISORDER_CATALOG:
        return raw
    key = raw.lower().replace("-", "_").replace(" ", "_")
    # Strip SNOMED-style suffixes for alias lookup.
    for suffix in ("_(disorder)", "_(finding)", "_(situation)"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    if key in _CONDITION_ALIASES:
        return _CONDITION_ALIASES[key]
    inferred = infer_disorders(raw)
    return inferred[0] if inferred else None


def infer_disorders(*parts: str) -> list[str]:
    """Return matching disorder labels from free text / condition names."""
    text = " ".join(part for part in parts if part).lower()
    if not text.strip():
        return []
    # Prefer explicit condition-slug aliases first.
    slug = text.strip().replace(" ", "_").replace("-", "_")
    for suffix in ("_(disorder)", "_(finding)", "_(situation)"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)]
    if slug in _CONDITION_ALIASES:
        return [_CONDITION_ALIASES[slug]]
    found: list[str] = []
    for label, needles in _DISORDER_RULES:
        if any(needle in text for needle in needles):
            found.append(label)
    return found


def disorders_for_condition(condition: str) -> list[str]:
    label = normalize_disorder_label(condition)
    if label:
        return [label]
    inferred = infer_disorders(condition.replace("_", " "))
    if inferred:
        return inferred
    if "(disorder)" in (condition or "").lower():
        return ["Other clinical"]
    return []


def is_clinical_procedure(name: str) -> bool:
    """Skip chart-admin procedures that are not lifelong clinical history."""
    lower = (name or "").lower()
    if not lower.strip():
        return False
    noise = (
        "medication reconciliation",
        "medication review",
        "documentation",
        "encounter for",
        "patient referral",
        "telephone consultation",
    )
    return not any(token in lower for token in noise)
