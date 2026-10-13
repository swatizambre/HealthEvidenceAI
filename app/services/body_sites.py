"""Anatomical body-site labels for lifelong history chapters.

These are body regions (spine, abdomen, limb) — not hospitals or clinics.
"""

from __future__ import annotations

# Stable chapter labels shown in filters (order = display preference).
BODY_SITE_CATALOG: tuple[str, ...] = (
    "Spine / back",
    "Abdomen / pelvis",
    "Chest",
    "Head / neck",
    "Upper limb",
    "Lower limb",
    "Soft tissue",
    "Obstetric",
    "Systemic",
)

_UNSPECIFIED = "Unspecified"

# Longer needles first so "low back" wins over bare "back".
_BODY_SITE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Spine / back",
        (
            "low back",
            "lumbar",
            "spine",
            "disc",
            "vertebral",
            "sciatica",
            "spondyl",
            "back pain",
            "cervical spine",
            "thoracic spine",
        ),
    ),
    (
        "Obstetric",
        (
            "lscs",
            "cesarean",
            "caesarean",
            "c-section",
            "obstetric",
            "pregnancy",
            "delivery",
            "postpartum",
            "pelvic floor",
        ),
    ),
    (
        "Abdomen / pelvis",
        (
            "append",
            "abdomen",
            "abdominal",
            "pelvis",
            "pelvic",
            "gastritis",
            "gastric",
            "hernia",
            "gallbladder",
            "bowel",
            "uterus",
            "ovary",
        ),
    ),
    (
        "Chest",
        (
            "chest",
            "cardiac",
            "heart",
            "lung",
            "pulmonary",
            "thorax",
            "rib",
            "cabg",
            "angioplasty",
        ),
    ),
    (
        "Head / neck",
        ("brain", "head", "skull", "neck", "stroke", "cranial", "thyroid", "ent"),
    ),
    (
        "Upper limb",
        ("shoulder", "elbow", "wrist", "hand", "arm", "forearm", "clavicle", "rotator"),
    ),
    (
        "Lower limb",
        ("knee", "hip", "ankle", "foot", "leg", "thigh", "femur", "tibia", "achilles"),
    ),
    (
        "Soft tissue",
        ("soft tissue", "trauma", "accident", "laceration", "sprain", "strain", "contusion"),
    ),
    (
        "Systemic",
        (
            "diabetes",
            "hypertension",
            "asthma",
            "infection",
            "fever",
            "anemia",
            "thyroid",
            "chronic",
            "condition",
        ),
    ),
)


def normalize_body_site(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return _UNSPECIFIED
    if raw in BODY_SITE_CATALOG:
        return raw
    return infer_body_site(raw)


def infer_body_site(*parts: str) -> str:
    """Infer a body-site chapter from free text (title, summary, procedure name)."""
    text = " ".join(part for part in parts if part).lower()
    if not text.strip():
        return _UNSPECIFIED
    for site, needles in _BODY_SITE_RULES:
        if any(needle in text for needle in needles):
            return site
    return _UNSPECIFIED


def is_filterable_body_site(value: str | None) -> bool:
    site = normalize_body_site(value)
    return site in BODY_SITE_CATALOG and site != _UNSPECIFIED
