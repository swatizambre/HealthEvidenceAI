"""Map hospital FHIR R4 encounter bundles into OpdIngestRequest."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from app.core.exceptions import AppError
from app.schemas.api import (
    OpdDiagnosisIn,
    OpdFhirIngestRequest,
    OpdIngestRequest,
    OpdLabIn,
    OpdMedicationIn,
    OpdVitalIn,
)


def fhir_bundle_to_opd_request(payload: OpdFhirIngestRequest) -> OpdIngestRequest:
    """Translate a FHIR R4 Bundle (or resource collection) to an OPD packet."""
    resources = _resources(payload.bundle)
    if not resources:
        raise AppError(
            "OPD_FHIR_INVALID",
            "FHIR payload must be a Bundle with entry[].resource or a resource collection.",
            400,
        )

    patient = _first(resources, "Patient")
    encounter = _first(resources, "Encounter")
    if patient is None:
        raise AppError("OPD_FHIR_INVALID", "FHIR Bundle must include a Patient resource.", 400)

    mrn = _patient_mrn(patient) or str(patient.get("id") or "").strip()
    if not mrn:
        raise AppError("OPD_FHIR_INVALID", "Patient must include an identifier or id.", 400)

    encounter_id = _encounter_id(encounter) or f"FHIR-{mrn}"
    note_parts: list[str] = []
    for doc in _all(resources, "DocumentReference"):
        text = _doc_text(doc)
        if text:
            note_parts.append(text)
    for composition in _all(resources, "Composition"):
        title = str(composition.get("title") or "Composition").strip()
        note_parts.append(title)

    diagnoses_raw = [_condition_to_dx(item) for item in _all(resources, "Condition")]
    diagnoses = [item for item in diagnoses_raw if item is not None]
    labs: list[OpdLabIn] = []
    vitals: list[OpdVitalIn] = []
    for obs in _all(resources, "Observation"):
        category = _coding_codes(obs.get("category"))
        if "vital-signs" in category:
            vital = _observation_to_vital(obs)
            if vital:
                vitals.append(vital)
        else:
            lab = _observation_to_lab(obs)
            if lab:
                labs.append(lab)

    medications: list[OpdMedicationIn] = []
    for med in _all(resources, "MedicationStatement") + _all(resources, "MedicationRequest"):
        mapped = _medication_to_opd(med)
        if mapped:
            medications.append(mapped)

    sex = _map_sex(patient.get("gender"))
    birth = _parse_date(patient.get("birthDate"))
    display = _patient_name(patient)
    attending = _attending(encounter)
    facility = _facility(encounter)
    department = _department(encounter) or _class_department(encounter)
    chief = _chief_complaint(encounter, resources)

    # EHR exports often omit DocumentReference; still land a usable visit note.
    if not note_parts:
        synth: list[str] = []
        if chief:
            synth.append(f"Chief complaint: {chief}")
        for dx in diagnoses[:8]:
            synth.append(f"Diagnosis: {dx.display}" + (f" ({dx.code})" if dx.code else ""))
        if labs:
            synth.append(
                "Labs: "
                + "; ".join(
                    f"{lab.test_name}={lab.value}{(' ' + lab.unit) if lab.unit else ''}"
                    for lab in labs[:6]
                )
            )
        if medications:
            synth.append(
                "Medications: " + "; ".join(med.name for med in medications[:6] if med.name)
            )
        if synth:
            note_parts.append("\n".join(synth))
        else:
            note_parts.append("FHIR encounter imported without narrative documents.")

    return OpdIngestRequest(
        external_patient_id=mrn[:64],
        encounter_id=encounter_id[:64],
        encounter_at=_parse_datetime((encounter or {}).get("period", {}).get("start")),
        facility_name=facility or "Hospital",
        department=department or "OPD",
        visit_type=_visit_type(encounter),
        attending_provider=attending,
        chief_complaint=chief,
        note="\n\n".join(note_parts),
        diagnoses=diagnoses,
        vitals=vitals,
        labs=labs,
        medications=medications,
        procedure=payload.procedure,
        policy_id=payload.policy_id,
        patient_id=payload.patient_id,
        source="fhir_r4",
        synthetic=payload.synthetic,
        consent_attested=payload.consent_attested,
        consent_id=payload.consent_id,
        consent=payload.consent,
        sex=sex,
        birth_date=birth,
        display_name=display,
    )


def _resources(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict):
        return []
    if bundle.get("resourceType") == "Bundle":
        entries = bundle.get("entry") or []
        out: list[dict[str, Any]] = []
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
                out.append(entry["resource"])
        return out
    if "resourceType" in bundle:
        return [bundle]
    nested = bundle.get("resources")
    if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict) and item.get("resourceType")]
    return []


def _first(resources: list[dict[str, Any]], resource_type: str) -> dict[str, Any] | None:
    for item in resources:
        if item.get("resourceType") == resource_type:
            return item
    return None


def _all(resources: list[dict[str, Any]], resource_type: str) -> list[dict[str, Any]]:
    return [item for item in resources if item.get("resourceType") == resource_type]


def _patient_mrn(patient: dict[str, Any]) -> str:
    for identifier in patient.get("identifier") or []:
        if not isinstance(identifier, dict):
            continue
        value = str(identifier.get("value") or "").strip()
        if not value:
            continue
        system = str(identifier.get("system") or "").lower()
        type_text = str((identifier.get("type") or {}).get("text") or "").lower()
        codes = _coding_codes((identifier.get("type") or {}).get("coding"))
        if (
            "mrn" in system
            or "uhid" in system
            or "mrn" in type_text
            or "uhid" in type_text
            or "MR" in codes
            or value
        ):
            return value
    return ""


def _encounter_id(encounter: dict[str, Any] | None) -> str:
    if not encounter:
        return ""
    for identifier in encounter.get("identifier") or []:
        if isinstance(identifier, dict) and identifier.get("value"):
            return str(identifier["value"]).strip()
    return str(encounter.get("id") or "").strip()


def _patient_name(patient: dict[str, Any]) -> str:
    names = patient.get("name") or []
    if not names or not isinstance(names[0], dict):
        return ""
    name = names[0]
    if name.get("text"):
        return str(name["text"])[:120]
    family = str(name.get("family") or "")
    given = " ".join(str(part) for part in (name.get("given") or []) if part)
    return f"{given} {family}".strip()[:120]


def _map_sex(value: object) -> str:
    text = str(value or "unknown").lower()
    if text in {"male", "female", "other", "unknown"}:
        return text
    return "unknown"


def _coding_codes(value: object) -> list[str]:
    codes: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                if item.get("code"):
                    codes.append(str(item["code"]))
                nested = item.get("coding")
                if isinstance(nested, list):
                    codes.extend(_coding_codes(nested))
    return codes


def _condition_to_dx(condition: dict[str, Any]) -> OpdDiagnosisIn | None:
    coding = ((condition.get("code") or {}).get("coding") or [])
    display = str((condition.get("code") or {}).get("text") or "").strip()
    code = ""
    system = "local"
    if coding and isinstance(coding[0], dict):
        code = str(coding[0].get("code") or "")
        display = display or str(coding[0].get("display") or "")
        system_uri = str(coding[0].get("system") or "").lower()
        if "icd-10" in system_uri:
            system = "ICD-10"
        elif "snomed" in system_uri:
            system = "SNOMED"
    if not display and not code:
        return None
    return OpdDiagnosisIn(display=display or code, code=code, code_system=system)  # type: ignore[arg-type]


def _observation_to_lab(obs: dict[str, Any]) -> OpdLabIn | None:
    coding = ((obs.get("code") or {}).get("coding") or [])
    name = str((obs.get("code") or {}).get("text") or "").strip()
    loinc = ""
    if coding and isinstance(coding[0], dict):
        name = name or str(coding[0].get("display") or coding[0].get("code") or "")
        if "loinc" in str(coding[0].get("system") or "").lower():
            loinc = str(coding[0].get("code") or "")
    value, unit = _obs_value(obs)
    if not name or not value:
        return None
    return OpdLabIn(test_name=name[:120], value=value[:64], unit=unit[:64], loinc_code=loinc[:32])


def _observation_to_vital(obs: dict[str, Any]) -> OpdVitalIn | None:
    coding = ((obs.get("code") or {}).get("coding") or [])
    name = str((obs.get("code") or {}).get("text") or "").strip()
    if coding and isinstance(coding[0], dict):
        name = name or str(coding[0].get("display") or coding[0].get("code") or "")
    value, unit = _obs_value(obs)
    if not name or not value:
        return None
    return OpdVitalIn(name=name[:64], value=value[:64], unit=unit[:32])


def _obs_value(obs: dict[str, Any]) -> tuple[str, str]:
    if obs.get("valueString"):
        return str(obs["valueString"]), ""
    quantity = obs.get("valueQuantity") or {}
    if isinstance(quantity, dict) and quantity.get("value") is not None:
        return str(quantity.get("value")), str(quantity.get("unit") or quantity.get("code") or "")
    if obs.get("valueCodeableConcept"):
        text = (obs["valueCodeableConcept"] or {}).get("text")
        return str(text or ""), ""
    return "", ""


def _medication_to_opd(med: dict[str, Any]) -> OpdMedicationIn | None:
    concept = med.get("medicationCodeableConcept") or {}
    coding = concept.get("coding") or []
    name = str(concept.get("text") or "").strip()
    rxnorm = ""
    if coding and isinstance(coding[0], dict):
        name = name or str(coding[0].get("display") or coding[0].get("code") or "")
        if "rxnorm" in str(coding[0].get("system") or "").lower():
            rxnorm = str(coding[0].get("code") or "")
    if not name:
        return None
    status = str(med.get("status") or "active").lower()
    mapped_status = "discontinued" if status in {"stopped", "cancelled", "ended"} else "active"
    dosage = ""
    route = ""
    frequency = ""
    instructions = med.get("dosage") or med.get("dosageInstruction") or []
    if instructions and isinstance(instructions[0], dict):
        dosage = str(instructions[0].get("text") or "")
        route_coding = ((instructions[0].get("route") or {}).get("coding") or [])
        if route_coding and isinstance(route_coding[0], dict):
            route = str(route_coding[0].get("display") or "")
        timing = ((instructions[0].get("timing") or {}).get("code") or {}).get("text")
        frequency = str(timing or "")
    return OpdMedicationIn(
        name=name[:120],
        status=mapped_status,  # type: ignore[arg-type]
        dose=(dosage or "as prescribed")[:120],
        frequency=frequency[:64],
        route=route[:64],
        rxnorm_code=rxnorm[:32],
    )


def _attending(encounter: dict[str, Any] | None) -> str:
    if not encounter:
        return ""
    for participant in encounter.get("participant") or []:
        if not isinstance(participant, dict):
            continue
        display = ((participant.get("individual") or {}).get("display")) or ""
        if display:
            return str(display)[:120]
    return ""


def _facility(encounter: dict[str, Any] | None) -> str:
    if not encounter:
        return ""
    return str((encounter.get("serviceProvider") or {}).get("display") or "")[:120]


def _department(encounter: dict[str, Any] | None) -> str:
    if not encounter:
        return "OPD"
    service = encounter.get("serviceType") or {}
    if isinstance(service, dict) and service.get("text"):
        return str(service["text"])[:80]
    for loc in encounter.get("location") or []:
        if isinstance(loc, dict):
            display = ((loc.get("location") or {}).get("display") or "")
            if display:
                return str(display)[:80]
    return _class_department(encounter) or "OPD"


def _class_department(encounter: dict[str, Any] | None) -> str:
    if not encounter:
        return ""
    class_code = str((encounter.get("class") or {}).get("code") or "").upper()
    if class_code in {"EMER", "ER", "ED"}:
        return "Emergency"
    if class_code in {"IMP", "INPATIENT"}:
        return "Inpatient"
    if class_code in {"AMB", "AMBULATORY", "OUTPATIENT", "VR", "VIRT"}:
        return "OPD"
    return ""


def _visit_type(
    encounter: dict[str, Any] | None,
) -> Literal["outpatient", "ambulatory", "telehealth", "day_care"]:
    """Map FHIR Encounter.class into OpdIngestRequest.visit_type literals."""
    if not encounter:
        return "outpatient"
    class_code = str((encounter.get("class") or {}).get("code") or "").upper()
    if class_code in {"VR", "VIRT", "TELE"}:
        return "telehealth"
    if class_code in {"SS", "DAYCARE", "DAY"}:
        return "day_care"
    if class_code in {"AMB", "AMBULATORY"}:
        return "ambulatory"
    # EMER / IMP still land as outpatient packet until acute-care visit_type exists.
    return "outpatient"


def _chief_complaint(encounter: dict[str, Any] | None, resources: list[dict[str, Any]]) -> str:
    if encounter:
        reason = encounter.get("reasonCode") or []
        if reason and isinstance(reason[0], dict):
            text = reason[0].get("text")
            if text:
                return str(text)[:500]
            coding = reason[0].get("coding") or []
            if coding and isinstance(coding[0], dict) and coding[0].get("display"):
                return str(coding[0]["display"])[:500]
    for condition in _all(resources, "Condition"):
        text = ((condition.get("code") or {}).get("text") or "")
        if text:
            return str(text)[:500]
    return ""


def _doc_text(doc: dict[str, Any]) -> str:
    description = str(doc.get("description") or "").strip()
    content = doc.get("content") or []
    if content and isinstance(content[0], dict):
        attachment = content[0].get("attachment") or {}
        title = str(attachment.get("title") or "")
        return "\n".join(part for part in [description, title] if part)
    return description


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
