"""Lifelong, multi-facility health biography for continuity of care.

Any clinician (e.g. physiotherapy) can see past surgeries, symptoms, accidents,
and treatments recorded across hospitals — not only the current facility visit.
Patients can open the same longitudinal view for their own record.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.repository import list_documents_for_patient, list_procedures
from app.schemas.api import LifelongEventOut, LifelongGroupOut, LifelongSummaryResponse
from app.services.body_sites import infer_body_site, is_filterable_body_site, normalize_body_site
from app.services.disorders import (
    disorders_for_condition,
    infer_disorders,
    is_clinical_condition,
    is_clinical_procedure,
)
from app.services.records import require_patient
from app.services.specialties import normalize_specialty

_DEMO_SYNTHETIC_SOURCE = "demo_synthetic_biography"
_DEMO_WARNING = (
    "DEMO ONLY — invented example history, not from this patient's chart. "
    "Do not use for care or insurance decisions."
)

_CATEGORIES = (
    "surgery",
    "symptom",
    "injury",
    "treatment",
    "obstetric",
    "chronic",
    "hospitalization",
    "other",
)

# Not real care places — hospitals stay as metadata only, never as body-site filters.
_PLACEHOLDER_FACILITIES = frozenset(
    {
        "",
        "Chart procedure record",
        "Problem list",
        "Facility not labeled",
    }
)

# Support labels kept on events but omitted from specialty chapter chips.
_SUPPORT_SPECIALTIES = frozenset({"Laboratory", "Pharmacy", "Radiology", "Pathology", "Nuclear medicine"})


def get_lifelong_summary(session: Session, patient_code: str) -> LifelongSummaryResponse:
    patient = require_patient(session, patient_code)
    events: list[LifelongEventOut] = []

    for procedure in list_procedures(session, patient.id):
        if not is_clinical_procedure(procedure.name):
            continue
        specialty = _specialty_for_procedure(procedure.name)
        facility = _facility_for_procedure(procedure.name, patient.sex)
        body_site = infer_body_site(procedure.name)
        events.append(
            LifelongEventOut(
                event_id=procedure.procedure_code,
                category=_category_for_procedure(procedure.name),
                title=procedure.name,
                summary=f"Procedure recorded: {procedure.name}",
                occurred_on=_as_date(procedure.performed_at),
                facility_name=facility,
                specialty=specialty,
                body_site=body_site,
                disorders=infer_disorders(procedure.name),
                source="procedure",
                why_it_matters="Prior procedure — relevant for anesthesia, rehab, and imaging context.",
            )
        )

    for document in list_documents_for_patient(session, patient.id):
        meta = document.document_metadata or {}
        facility = str(meta.get("facility_name") or "").strip()
        specialty = normalize_specialty(
            str(meta.get("specialty") or meta.get("department") or "General medicine")
        )
        meta_site = str(meta.get("body_site") or meta.get("body_part") or "").strip()
        if document.document_type == "lifelong_event" or meta.get("lifelong"):
            title = str(meta.get("title") or document.document_type).strip()
            summary = (document.content or "")[:400]
            events.append(
                LifelongEventOut(
                    event_id=document.document_code,
                    category=_safe_category(str(meta.get("category") or "other")),
                    title=title,
                    summary=summary,
                    occurred_on=_parse_date(meta.get("occurred_on")) or _as_date(document.created_at),
                    facility_name=facility,
                    specialty=specialty,
                    body_site=normalize_body_site(meta_site)
                    if meta_site
                    else infer_body_site(title, summary),
                    disorders=infer_disorders(title, summary, str(meta.get("disorder") or "")),
                    source="lifelong_event",
                    why_it_matters=str(
                        meta.get("why_it_matters") or "Cross-facility history for continuity of care."
                    ),
                )
            )
            continue
        # Pull facility-tagged clinical notes into the lifelong lens when they look historical.
        if document.document_type == "clinical_note":
            for extracted in _extract_from_text(
                document.content or "",
                facility=facility,
                specialty=specialty,
                document_code=document.document_code,
                when=document.created_at,
            ):
                events.append(extracted)

    for condition in patient.conditions or []:
        if not is_clinical_condition(condition):
            continue
        title = condition.replace("_", " ").title()
        # Clean SNOMED-style titles for display.
        for suffix in (" (Disorder)", " (Finding)", " (Situation)"):
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        tagged = disorders_for_condition(condition)
        events.append(
            LifelongEventOut(
                event_id=f"cond-{_slug(condition)}",
                category="chronic",
                title=title,
                summary=f"Active clinical condition: {title}",
                occurred_on=None,
                facility_name="",
                specialty="General medicine",
                body_site=infer_body_site(title, condition),
                disorders=tagged,
                source="problem_list",
                why_it_matters="Known clinical problem — informs meds, rehab, and red-flag screening.",
            )
        )

    # Invented biography is local/test demo only — never under ALLOW_PHI / real charts.
    settings = get_settings()
    includes_demo_synthetic = False
    if settings.synthetic_lifelong_enabled():
        demo_events = _synthetic_cross_facility_story(
            patient.patient_code, patient.sex, patient.birth_date
        )
        events.extend(demo_events)
        includes_demo_synthetic = bool(demo_events)

    # Normalize labels and attach disorder tags used for lifelong filters.
    normalized: list[LifelongEventOut] = []
    for item in events:
        facility = (item.facility_name or "").strip()
        if facility in _PLACEHOLDER_FACILITIES:
            facility = ""
        body_site = normalize_body_site(item.body_site)
        if body_site == "Unspecified":
            body_site = infer_body_site(item.title, item.summary, item.category)
        disorders = list(item.disorders or [])
        if not disorders:
            disorders = infer_disorders(item.title, item.summary, item.category)
        # Deduplicate while preserving order.
        seen_d: set[str] = set()
        clean_disorders: list[str] = []
        for label in disorders:
            if label and label not in seen_d:
                seen_d.add(label)
                clean_disorders.append(label)
        normalized.append(
            item.model_copy(
                update={
                    "specialty": normalize_specialty(item.specialty or "General medicine"),
                    "facility_name": facility,
                    "body_site": body_site,
                    "disorders": clean_disorders,
                }
            )
        )
    events = _dedupe_events(normalized)
    events.sort(key=lambda item: (item.occurred_on or date(1900, 1, 1), item.title), reverse=True)

    by_facility = _group_events(events, lens="facility")
    by_specialty = _group_events(events, lens="specialty")
    by_body_site = _group_events(events, lens="body_site")
    by_disorder = _group_events(events, lens="disorder")
    facilities = [group.key for group in by_facility]
    specialties = [group.key for group in by_specialty]
    body_sites = [group.key for group in by_body_site]
    disorders = [group.key for group in by_disorder]
    brief = _doctor_brief(patient.synthetic_name, events, facilities, disorders)
    if includes_demo_synthetic:
        brief = f"{_DEMO_WARNING}\n\n{brief}"

    return LifelongSummaryResponse(
        patient_id=patient.patient_code,
        patient_name=patient.synthetic_name,
        facilities_count=len(facilities),
        facilities=facilities,
        specialties=specialties,
        specialties_count=len(specialties),
        body_sites=body_sites,
        body_sites_count=len(body_sites),
        disorders=disorders,
        disorders_count=len(disorders),
        events=events,
        by_facility=by_facility,
        by_specialty=by_specialty,
        by_body_site=by_body_site,
        by_disorder=by_disorder,
        doctor_brief=brief,
        patient_brief=(
            (
                f"{_DEMO_WARNING} "
                if includes_demo_synthetic
                else ""
            )
            + "Filter by the labels at the top (diabetes, thyroid, back pain, infection, and more) "
            "to open the matching clinical history for your next visit."
        ),
        includes_demo_synthetic=includes_demo_synthetic,
        demo_synthetic_disclaimer=_DEMO_WARNING if includes_demo_synthetic else "",
    )


def _group_events(events: list[LifelongEventOut], *, lens: str) -> list[LifelongGroupOut]:
    buckets: dict[str, list[LifelongEventOut]] = {}
    for item in events:
        if lens == "facility":
            key = (item.facility_name or "").strip()
            if not key or key in _PLACEHOLDER_FACILITIES:
                continue
            buckets.setdefault(key, []).append(item)
        elif lens == "body_site":
            key = normalize_body_site(item.body_site)
            if not is_filterable_body_site(key):
                continue
            buckets.setdefault(key, []).append(item)
        elif lens == "disorder":
            labels = item.disorders or infer_disorders(item.title, item.summary)
            for key in labels:
                buckets.setdefault(key, []).append(item)
        else:
            key = normalize_specialty(item.specialty or "General medicine")
            if key in _SUPPORT_SPECIALTIES:
                continue
            buckets.setdefault(key, []).append(item)
    groups: list[LifelongGroupOut] = []
    for key in sorted(buckets.keys(), key=lambda value: (-len(buckets[value]), value.lower())):
        rows = buckets[key]
        groups.append(
            LifelongGroupOut(
                key=key,
                label=key,
                count=len(rows),
                events=rows,
            )
        )
    return groups


def _specialty_for_procedure(name: str) -> str:
    lower = name.lower()
    if any(token in lower for token in ("cesarean", "lscs", "hysterectomy", "obstetric")):
        return normalize_specialty("Obstetrics & gynecology")
    if any(token in lower for token in ("knee", "hip", "fracture", "ortho", "spine", "disc")):
        return normalize_specialty("Orthopedics")
    if any(token in lower for token in ("physio", "rehab", "physical therapy")):
        return normalize_specialty("Physiotherapy")
    if any(token in lower for token in ("cardiac", "cabg", "angioplasty")):
        return normalize_specialty("Cardiac surgery")
    return normalize_specialty("Surgery")


def _facility_for_procedure(name: str, sex: str) -> str:
    """Map chart procedures onto Indian care places when the type is clear; else omit location."""
    lower = name.lower()
    if any(token in lower for token in ("cesarean", "lscs", "hysterectomy")):
        return "District Women & Child Hospital"
    if "append" in lower:
        return "District Civil Hospital — Satara"
    if any(token in lower for token in ("spine", "disc", "lumbar", "knee", "hip", "fracture")):
        return "Ortho & Spine Clinic — Pune"
    if any(token in lower for token in ("physio", "rehab")):
        return "Physiotherapy Unit — CHC Haveli"
    if any(token in lower for token in ("trauma", "accident", "laceration")):
        return "Casualty — District Civil Hospital"
    if str(sex).lower().startswith("f") and "deliver" in lower:
        return "District Women & Child Hospital"
    return ""


def _synthetic_cross_facility_story(
    patient_code: str, sex: str, birth_date: date
) -> list[LifelongEventOut]:
    digest = int(hashlib.sha256(patient_code.encode("utf-8")).hexdigest()[:8], 16)
    age = max(18, date.today().year - birth_date.year)
    base_year = date.today().year

    story: list[dict[str, Any]] = [
        {
            "category": "injury",
            "title": "Road traffic accident — soft tissue injury",
            "summary": "Treated in emergency; no surgery. Residual stiffness reported.",
            "years_ago": 2 + (digest % 4),
            "facility": "Casualty — District Civil Hospital",
            "specialty": "Emergency medicine",
            "body_site": "Soft tissue",
            "disorders": ["Trauma / injury"],
            "why": "Prior trauma — relevant for pain patterns and imaging comparison.",
        },
        {
            "category": "symptom",
            "title": "Low back pain — suspected disc degeneration",
            "summary": "Intermittent low back pain after prolonged sitting/sleep; managed conservatively.",
            "years_ago": 5 + (digest % 3),
            "facility": "Primary Health Centre — Wadki",
            "specialty": "General medicine",
            "body_site": "Spine / back",
            "disorders": ["Disc disease / back pain"],
            "why": "PHC OPD history — critical before CHC/district referral and physio.",
        },
        {
            "category": "treatment",
            "title": "Physiotherapy course — lumbar stabilization",
            "summary": "Supervised physio for core strengthening; partial relief.",
            "years_ago": 4 + (digest % 2),
            "facility": "Physiotherapy Unit — CHC Haveli",
            "specialty": "Physiotherapy",
            "body_site": "Spine / back",
            "disorders": ["Disc disease / back pain"],
            "why": "Prior rehab response helps plan the next physio protocol.",
        },
    ]

    # Chronic disorder chapters so filters include diabetes / thyroid / hypertension style problems.
    chronic_pool = (
        {
            "category": "chronic",
            "title": "Type 2 diabetes mellitus",
            "summary": "Followed in medicine clinic; lifestyle and oral agents documented.",
            "years_ago": 3 + (digest % 5),
            "facility": "Krishna Multispecialty Hospital, Pune",
            "specialty": "Endocrinology",
            "body_site": "Systemic",
            "disorders": ["Diabetes"],
            "why": "Metabolic history — relevant for infection risk, wound healing, and meds.",
        },
        {
            "category": "chronic",
            "title": "Hypothyroidism",
            "summary": "On replacement therapy; TSH monitored periodically.",
            "years_ago": 4 + (digest % 4),
            "facility": "Krishna Multispecialty Hospital, Pune",
            "specialty": "Endocrinology",
            "body_site": "Head / neck",
            "disorders": ["Thyroid disorder"],
            "why": "Thyroid status affects fatigue, weight, and perioperative planning.",
        },
        {
            "category": "chronic",
            "title": "Essential hypertension",
            "summary": "Blood pressure treated with antihypertensives; home readings advised.",
            "years_ago": 2 + (digest % 6),
            "facility": "Community Health Centre — Haveli",
            "specialty": "General medicine",
            "body_site": "Systemic",
            "disorders": ["Hypertension"],
            "why": "Cardiovascular risk context for anesthesia and rehab load.",
        },
    )
    story.append(chronic_pool[digest % len(chronic_pool)])
    if digest % 3 == 0:
        story.append(chronic_pool[(digest + 1) % len(chronic_pool)])

    if str(sex).lower().startswith("f") and age >= 22:
        story.append(
            {
                "category": "obstetric",
                "title": "LSCS (lower segment cesarean section)",
                "summary": "Lower segment cesarean delivery; post-op recovery documented as uneventful.",
                "years_ago": min(age - 20, 8 + (digest % 5)),
                "facility": "District Women & Child Hospital",
                "specialty": "Obstetrics & gynecology",
                "body_site": "Obstetric",
                "disorders": ["Obstetric history"],
                "why": "Prior LSCS — relevant for abdominal wall, pelvic floor, and future surgery planning.",
            }
        )
    else:
        story.append(
            {
                "category": "surgery",
                "title": "Appendectomy",
                "summary": "Laparoscopic appendectomy; no major complications recorded.",
                "years_ago": 6 + (digest % 6),
                "facility": "District Civil Hospital — Satara",
                "specialty": "Surgery",
                "body_site": "Abdomen / pelvis",
                "disorders": ["Gastritis / GI"],
                "why": "Surgical scar / adhesion context for abdominal symptoms.",
            }
        )

    if digest % 2 == 0:
        story.append(
            {
                "category": "hospitalization",
                "title": "Short-stay admission — severe gastritis",
                "summary": "IV fluids and PPI; discharged stable.",
                "years_ago": 1 + (digest % 3),
                "facility": "Krishna Multispecialty Hospital, Pune",
                "specialty": "General medicine",
                "body_site": "Abdomen / pelvis",
                "disorders": ["Gastritis / GI"],
                "why": "Prior admission informs medication risk and follow-up labs.",
            }
        )

    out: list[LifelongEventOut] = []
    for index, item in enumerate(story):
        years_ago = int(item["years_ago"])
        occurred = date(base_year - years_ago, 6, 15)
        title = str(item["title"])
        summary = str(item["summary"])
        disorders = [str(label) for label in (item.get("disorders") or [])]
        if not disorders:
            disorders = infer_disorders(title, summary)
        out.append(
            LifelongEventOut(
                event_id=f"life-{patient_code}-{index}",
                category=str(item["category"]),
                title=title,
                summary=summary,
                occurred_on=occurred,
                facility_name=str(item["facility"]),
                specialty=normalize_specialty(str(item["specialty"])),
                body_site=normalize_body_site(str(item.get("body_site") or ""))
                if item.get("body_site")
                else infer_body_site(title, summary),
                disorders=disorders,
                source=_DEMO_SYNTHETIC_SOURCE,
                why_it_matters=_DEMO_WARNING,
                demo_synthetic=True,
            )
        )
    return out


def _extract_from_text(
    content: str,
    *,
    facility: str,
    specialty: str,
    document_code: str,
    when: datetime | None,
) -> list[LifelongEventOut]:
    lower = content.lower()
    found: list[LifelongEventOut] = []
    checks = (
        ("lscs", "obstetric", "LSCS mentioned in note", "Prior cesarean — surgical/rehab relevance."),
        ("cesarean", "obstetric", "Cesarean mentioned", "Prior cesarean — surgical/rehab relevance."),
        ("slipped disc", "symptom", "Slipped disc mentioned", "Spine history for physio and imaging."),
        ("disc prolapse", "symptom", "Disc prolapse mentioned", "Spine history for physio and imaging."),
        ("back pain", "symptom", "Back pain documented", "Symptom history for precise rehab planning."),
        ("accident", "injury", "Accident / trauma mentioned", "Trauma history for pain and imaging."),
        ("fracture", "injury", "Fracture mentioned", "Orthopedic history for load-bearing advice."),
    )
    for needle, category, title, why in checks:
        if needle in lower:
            found.append(
                LifelongEventOut(
                    event_id=f"{document_code}-{needle.replace(' ', '-')}",
                    category=category,
                    title=title,
                    summary=content[:280],
                    occurred_on=_as_date(when),
                    facility_name=facility,
                    specialty=specialty,
                    body_site=infer_body_site(title, content[:280], needle),
                    disorders=infer_disorders(title, content[:280], needle),
                    source="note_signal",
                    why_it_matters=why,
                )
            )
    return found


def _category_for_procedure(name: str) -> str:
    lower = name.lower()
    if "cesarean" in lower or "lscs" in lower or "hysterectomy" in lower:
        return "obstetric"
    if "physio" in lower or "rehab" in lower:
        return "treatment"
    return "surgery"


def _safe_category(value: str) -> str:
    key = value.strip().lower()
    return key if key in _CATEGORIES else "other"


def _doctor_brief(
    name: str,
    events: list[LifelongEventOut],
    facilities: list[str],
    disorders: list[str],
) -> str:
    clinical = [e for e in events if e.source != "problem_list" or e.disorders]
    surgeries = [e.title for e in clinical if e.category in {"surgery", "obstetric"}][:3]
    symptoms = [e.title for e in clinical if e.category in {"symptom", "injury", "chronic"}][:3]
    if disorders:
        parts = [
            f"{name}: lifelong clinical history — filter by label "
            f"({', '.join(disorders[:4])}{'…' if len(disorders) > 4 else ''})."
        ]
    else:
        parts = [f"{name}: lifelong clinical history across {len(facilities)} care places."]
    if surgeries:
        parts.append("Key procedures: " + "; ".join(surgeries) + ".")
    if symptoms:
        parts.append("Key symptoms/conditions: " + "; ".join(symptoms) + ".")
    return " ".join(parts)


def _dedupe_events(events: list[LifelongEventOut]) -> list[LifelongEventOut]:
    seen: set[str] = set()
    out: list[LifelongEventOut] = []
    for event in events:
        key = f"{event.category}|{event.title.lower()}|{event.occurred_on}|{event.facility_name}"
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.date()
    return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")[:48]
