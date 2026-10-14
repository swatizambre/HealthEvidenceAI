"""India rural ↔ urban facility taxonomy and desk guidance.

Documentation-readiness desks for PHC/CHC/taluk/district and urban hospitals.
Never models clinical autonomy or insurance approval.
"""

from __future__ import annotations

from typing import Any

# Product facility_type codes (API + UI). Keep legacy codes for existing orgs.
FACILITY_TYPES: tuple[dict[str, str], ...] = (
    {
        "id": "phc",
        "label": "PHC / sub-centre OPD",
        "tier": "rural",
        "hint": "Single MO / ANM desk — document visit, attach basics, refer up with a clear pack.",
    },
    {
        "id": "chc",
        "label": "CHC / block hospital",
        "tier": "rural",
        "hint": "First referral level — close gaps from PHC notes before district handoff.",
    },
    {
        "id": "taluk",
        "label": "Taluk / tehsil hospital",
        "tier": "rural",
        "hint": "Mixed OPD + minor procedures — prepare packs for cashless / TPA checklists.",
    },
    {
        "id": "district",
        "label": "District hospital",
        "tier": "rural_urban",
        "hint": "Specialty OPDs + emergency — seniors confirm citations; clerks assemble packs.",
    },
    {
        "id": "clinic",
        "label": "Clinic / nursing home",
        "tier": "urban",
        "hint": "Small urban practice — one person may prep and self-check before insurer desk.",
    },
    {
        "id": "multispecialty",
        "label": "Urban multispecialty hospital",
        "tier": "urban",
        "hint": "Departmental desks — staff prep, PG/resident draft, consultant HITL.",
    },
    {
        "id": "superspecialty",
        "label": "Super-specialty / corporate centre",
        "tier": "urban",
        "hint": "High-volume cashless packs — tight specialty tagging and citation review.",
    },
    {
        "id": "government",
        "label": "Medical college / teaching hospital",
        "tier": "urban",
        "hint": "Teaching teams — residents prepare; unit consultant confirms the checklist.",
    },
)

_ROLE_LABELS_IN: dict[str, str] = {
    "patient": "Patient (my record)",
    "staff": "Records / TPA desk clerk",
    "resident": "Junior doctor / PG / MO (junior)",
    "senior_clinician": "Consultant / senior MO",
    "admin": "Facility / HIS admin",
}


def facility_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in FACILITY_TYPES]


def facility_label(facility_type: str) -> str:
    key = (facility_type or "").strip().lower()
    for item in FACILITY_TYPES:
        if item["id"] == key:
            return item["label"]
    return facility_type or "Facility"


def desk_subtitle(*, role: str, facility_type: str) -> str:
    """Short Today subtitle for Indian rural/urban desks."""
    tier = "urban"
    for item in FACILITY_TYPES:
        if item["id"] == (facility_type or "").strip().lower():
            tier = item["tier"]
            break
    role_key = (role or "staff").strip().lower()
    rural = tier in {"rural", "rural_urban"}

    if role_key == "senior_clinician":
        return (
            "Confirm chart citations before cashless / referral handoff — not an approval."
            if rural
            else "Consultant review of evidence packs — citations only, not coverage decisions."
        )
    if role_key == "resident":
        return (
            "Close documentation gaps and prepare packs for senior MO / consultant."
            if rural
            else "PG desk: prepare packs and flag open items for unit consultant."
        )
    if role_key == "admin":
        return "Facility queue, SLA, and org scope across OPD / referral desks."
    if role_key == "patient":
        return "Your lifelong record across PHC, district, and city hospitals."
    # staff
    return (
        "Assemble notes from this facility and hand a clear pack for senior / referral review."
        if rural
        else "Assemble chart evidence for cashless / TPA checklists; hand off for consultant review."
    )


def role_label_india(role: str) -> str:
    return _ROLE_LABELS_IN.get((role or "").strip().lower(), role)


def india_org_seeds() -> list[dict[str, Any]]:
    """Demo tenant orgs spanning rural referral chain + urban hospital."""
    return [
        {
            "org_code": "ORG-000001",
            "name": "Krishna Multispecialty Hospital, Pune",
            "facility_type": "multispecialty",
        },
        {
            "org_code": "ORG-000002",
            "name": "Primary Health Centre — Wadki",
            "facility_type": "phc",
        },
        {
            "org_code": "ORG-000003",
            "name": "Community Health Centre — Haveli",
            "facility_type": "chc",
        },
        {
            "org_code": "ORG-000004",
            "name": "District Civil Hospital — Satara",
            "facility_type": "district",
        },
    ]


def describe_india_desk() -> dict[str, Any]:
    return {
        "market": "india",
        "stance": "documentation_readiness_rural_urban",
        "facilities": facility_catalog(),
        "referral_ladder": ["phc", "chc", "taluk", "district", "multispecialty", "government"],
        "payer_language": "cashless / TPA / empanelment checklists (never approve or deny)",
        "disclaimer": (
            "Supports Indian rural and urban desks assembling chart evidence for "
            "referral and insurer documentation. Does not diagnose or decide coverage."
        ),
    }
