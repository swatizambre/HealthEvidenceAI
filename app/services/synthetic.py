"""Build the synthetic evidence catalog from the configured public data source.

Patient facts come from the public source. Policy criteria and demo case roles are
chosen from catalog statistics using the same evaluation rules as the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from app.models import (
    AuthorizationCase,
    Claim,
    ClinicalNote,
    Document,
    ImagingStudy,
    InsurancePolicy,
    LabResult,
    Medication,
    Patient,
    PolicyCriterion,
    Procedure,
)
from app.services.embeddings import EMBEDDING_METHOD
from app.services.policy_factory import (
    POLICY_MARKER,
    CaseProfiles,
    DynamicPolicy,
    build_dynamic_policy,
    select_case_profiles,
)
from app.services.synthea_source import (
    SOURCE_NAME,
    LabFact,
    SyntheaPatient,
    load_catalog,
)

SEEDED_AT = datetime(2026, 1, 15, tzinfo=UTC)
DEMO_PATIENT = "PAT-000001"
DEMO_POLICY = "POL-000001"
DEMO_CASE = "PA-000001"
PATIENT_COUNT = 100
POLICY_COUNT = 20
CASE_COUNT = 20


@lru_cache(maxsize=1)
def seed_plan() -> tuple[DynamicPolicy, CaseProfiles, tuple[SyntheaPatient, ...]]:
    """Cached catalog plan: dynamic policy, role profiles, and public patient order."""
    catalog = load_catalog()
    policy = build_dynamic_policy(catalog)
    profiles = select_case_profiles(catalog, policy)
    ordered = _ordered_patients(catalog.patients, profiles)
    return policy, profiles, tuple(ordered)


def get_demo_procedure() -> str:
    return seed_plan()[0].procedure


@dataclass
class SyntheticDataset:
    patients: list[Patient] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    notes: list[ClinicalNote] = field(default_factory=list)
    labs: list[LabResult] = field(default_factory=list)
    medications: list[Medication] = field(default_factory=list)
    procedures: list[Procedure] = field(default_factory=list)
    imaging_studies: list[ImagingStudy] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    policies: list[InsurancePolicy] = field(default_factory=list)
    criteria: list[PolicyCriterion] = field(default_factory=list)
    cases: list[AuthorizationCase] = field(default_factory=list)


def build_dataset() -> SyntheticDataset:
    """Load catalog patients and authorization cases driven by discovered criteria."""
    policy, _profiles, ordered = seed_plan()
    if len(ordered) != PATIENT_COUNT:
        raise RuntimeError(f"Expected {PATIENT_COUNT} patients, got {len(ordered)}.")
    required_lab = str(policy.criteria[3]["rule"]["test_name"])
    data = SyntheticDataset()
    patient_ids: dict[str, str] = {}
    imaging_added = 0
    claims_added = 0
    for number, source in enumerate(ordered, start=1):
        patient = _patient(number, source, policy)
        patient_ids[patient.patient_code] = patient.id
        data.patients.append(patient)
        _add_clinical_records(data, patient, source, number, required_lab)
        if imaging_added < 50 and source.imaging:
            imaging_added += 1
            _add_imaging(data, patient.id, source, imaging_added)
        if claims_added < 50 and source.claims:
            claims_added += 1
            _add_claim(data, patient.id, source, claims_added)
    if imaging_added < 50 or claims_added < 50:
        raise RuntimeError("The loaded catalog did not contain 50 imaging studies and 50 claims.")
    catalog = load_catalog()
    policy_ids: dict[str, str] = {}
    for number in range(1, POLICY_COUNT + 1):
        item = _policy(data, number, catalog.payer_names, policy)
        policy_ids[item.policy_code] = item.id
        data.policies.append(item)
    _add_cases(data, patient_ids, policy_ids, policy.procedure)
    return data


def _ordered_patients(
    patients: tuple[SyntheaPatient, ...],
    profiles: CaseProfiles,
) -> list[SyntheaPatient]:
    reserved = {
        profiles.missing_lab.source_id,
        profiles.complete.source_id,
        profiles.not_supported.source_id,
        profiles.contradicted.source_id,
    }
    rest = [patient for patient in patients if patient.source_id not in reserved]
    # Lead with the complete live sample so PA-000001 / PAT-000001 demonstrates a
    # working end-to-end review before the incomplete-evidence vignettes.
    ordered = [
        profiles.complete,
        profiles.missing_lab,
        profiles.not_supported,
        profiles.contradicted,
        *rest,
    ]
    return ordered[:PATIENT_COUNT]


def _patient(number: int, source: SyntheaPatient, policy: DynamicPolicy) -> Patient:
    priority = _priority_conditions(policy)
    chosen = [item for item in priority if item in source.conditions]
    for item in source.conditions:
        if item not in chosen:
            chosen.append(item)
        if len(chosen) == 12:
            break
    return Patient(
        id=str(uuid4()),
        patient_code=f"PAT-{number:06d}",
        synthetic_name=f"Synthetic Patient {number:06d}",
        birth_date=source.birth_date,
        sex=source.sex,
        conditions=chosen,
        created_at=SEEDED_AT,
        updated_at=SEEDED_AT,
    )


def _priority_conditions(policy: DynamicPolicy) -> list[str]:
    phrases: list[str] = []
    for criterion in policy.criteria:
        rule = criterion["rule"]
        for key in ("required_any", "negation_any", "clear_any", "uncertain_any"):
            for phrase in rule.get(key) or []:
                if phrase not in phrases:
                    phrases.append(str(phrase))
    return phrases


def _add_clinical_records(
    data: SyntheticDataset,
    patient: Patient,
    source: SyntheaPatient,
    number: int,
    required_lab: str,
) -> None:
    from app.services.specialties import seed_specialty_for_patient

    specialty = seed_specialty_for_patient(number)
    note_text = _note_text(patient.patient_code, patient.conditions, source.medications[0].description)
    note_document = _document(
        code=f"DOC-N{number:06d}",
        patient_id=patient.id,
        document_type="clinical_note",
        content=note_text,
        metadata={
            "note_code": f"NOTE-{number:06d}",
            "dataset": SOURCE_NAME,
            "embedding_method": EMBEDDING_METHOD,
            "department": specialty,
            "specialty": specialty,
        },
    )
    data.documents.append(note_document)
    data.notes.append(
        ClinicalNote(
            id=str(uuid4()),
            note_code=f"NOTE-{number:06d}",
            patient_id=patient.id,
            document_id=note_document.id,
            note_type="catalog_clinical_note",
            content=note_document.content,
            authored_at=source.medications[0].started_at,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
    )
    lab = _representative_lab(source, number, required_lab)
    lab_content = f"{lab.description}: {lab.value} {lab.unit}".strip()
    lab_document = _document(
        code=f"DOC-L{number:06d}",
        patient_id=patient.id,
        document_type="lab_result",
        content=lab_content,
        metadata={
            "lab_code": f"LAB-{number:06d}",
            "dataset": SOURCE_NAME,
            "embedding_method": EMBEDDING_METHOD,
            "department": "Laboratory",
            "specialty": "Laboratory",
        },
    )
    data.documents.append(lab_document)
    data.labs.append(
        LabResult(
            id=str(uuid4()),
            lab_code=f"LAB-{number:06d}",
            patient_id=patient.id,
            document_id=lab_document.id,
            test_name=lab.description[:120],
            value=lab.value,
            unit=lab.unit,
            collected_at=lab.collected_at,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
    )
    medication = source.medications[0]
    data.medications.append(
        Medication(
            id=str(uuid4()),
            medication_code=f"MED-{number:06d}",
            patient_id=patient.id,
            name=medication.description[:120],
            dose="recorded in source catalog",
            status="discontinued" if medication.stopped else "active",
            started_at=medication.started_at,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
    )
    procedure = source.procedures[0]
    data.procedures.append(
        Procedure(
            id=str(uuid4()),
            procedure_code=f"PROC-{number:06d}",
            patient_id=patient.id,
            name=procedure.description[:200],
            performed_at=procedure.performed_at,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
    )


def _add_imaging(
    data: SyntheticDataset,
    patient_id: str,
    source: SyntheaPatient,
    number: int,
) -> None:
    study = source.imaging[0]
    data.imaging_studies.append(
        ImagingStudy(
            id=str(uuid4()),
            imaging_code=f"IMG-{number:06d}",
            patient_id=patient_id,
            modality=study.modality,
            body_part=study.body_part,
            studied_at=study.studied_at,
            description=study.description,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
    )


def _add_claim(
    data: SyntheticDataset,
    patient_id: str,
    source: SyntheaPatient,
    number: int,
) -> None:
    claim = source.claims[0]
    data.claims.append(
        Claim(
            id=str(uuid4()),
            claim_code=f"CLM-{number:06d}",
            patient_id=patient_id,
            status=claim.status,
            amount_cents=claim.amount_cents,
            service_date=claim.service_date,
            created_at=SEEDED_AT,
            updated_at=SEEDED_AT,
        )
    )


def _representative_lab(source: SyntheaPatient, number: int, required_lab: str) -> LabFact:
    # Patient 2 is the missing-lab vignette (patient 1 is the complete live sample).
    if number == 2:
        alternate = next((lab for lab in source.labs if lab.description != required_lab), None)
        if alternate is None:
            raise RuntimeError("Demo patient has no alternate laboratory result for the MISSING case.")
        return alternate
    preferred = next((lab for lab in source.labs if lab.description == required_lab), None)
    if preferred is not None:
        return preferred
    return source.labs[0]


def _note_text(patient_code: str, conditions: list[str], medication: str) -> str:
    return "\n".join(
        [
            f"SYNTHEA_RECORD_{patient_code.replace('-', '_')}.",
            f"Source: {SOURCE_NAME}. Synthetic patient. Not a real medical record.",
            "Assessment:",
            *[f"The clinical record documents {condition}." for condition in conditions],
            "Current medication:",
            f"The patient is recorded as taking {medication}.",
        ]
    )


def _policy(
    data: SyntheticDataset,
    number: int,
    payer_names: tuple[str, ...],
    dynamic: DynamicPolicy,
) -> InsurancePolicy:
    # Synthea's payers.csv lists US payers (Medicare, Medicaid, ...). The desk serves
    # Indian hospitals, so show synthetic Indian insurer/TPA labels instead.
    from app.services.tpa_seed import indian_payer_label

    del payer_names
    payer_name = indian_payer_label(number - 1)
    if number == 1:
        code = DEMO_POLICY
        title = dynamic.title
        procedure_name = dynamic.procedure
        content = dynamic.content.strip()
        criteria = [dict(item) for item in dynamic.criteria]
    else:
        code = f"POL-{number:06d}"
        title = f"Catalog payer checklist {number:02d}"
        procedure_name = f"Catalog procedure {number:02d}"
        content = (
            f"Payer label (synthetic): {payer_name}. "
            f"Policy {code} is an evidence checklist for this prototype, "
            "not a coverage determination. "
            f"Marker {code}."
        )
        criteria = _generic_criteria(number)
    document = _document(
        code=f"DOC-P{number:06d}",
        patient_id=None,
        document_type="policy",
        content=content,
        metadata={"policy_code": code, "dataset": SOURCE_NAME, "embedding_method": EMBEDDING_METHOD},
    )
    data.documents.append(document)
    policy = InsurancePolicy(
        id=str(uuid4()),
        policy_code=code,
        title=title,
        payer_name=payer_name,
        procedure_name=procedure_name,
        version="catalog-dynamic",
        content=content,
        document_id=document.id,
        created_at=SEEDED_AT,
        updated_at=SEEDED_AT,
    )
    for position, spec in enumerate(criteria, start=1):
        data.criteria.append(
            PolicyCriterion(
                id=str(uuid4()),
                criterion_code=str(spec["code"]),
                policy_id=policy.id,
                description=str(spec["description"]),
                summary=str(spec["description"]),
                position=position,
                rule=dict(spec["rule"]),
                created_at=SEEDED_AT,
                updated_at=SEEDED_AT,
            )
        )
    return policy


def _generic_criteria(policy_number: int) -> list[dict[str, Any]]:
    count = 3 if policy_number <= 8 else 2
    criteria: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        code = f"CRIT-P{policy_number:02d}-{index:02d}"
        marker = f"marker {code}"
        criteria.append(
            {
                "code": code,
                "description": f"Checklist marker {code} is documented.",
                "rule": {
                    "type": "keyword",
                    "required_any": [marker],
                    "negation_any": [],
                    "missing_label": f"Marker for {code}",
                },
            }
        )
    return criteria


def _add_cases(
    data: SyntheticDataset,
    patient_ids: dict[str, str],
    policy_ids: dict[str, str],
    demo_procedure: str,
) -> None:
    planned: list[tuple[int, int, int, str]] = [
        (1, 1, 1, demo_procedure),
        (2, 2, 1, demo_procedure),
        (3, 3, 1, demo_procedure),
        (4, 4, 1, demo_procedure),
    ]
    for number in range(5, CASE_COUNT + 1):
        policy_number = ((number - 1) % POLICY_COUNT) + 1
        planned.append((number, number, policy_number, f"Catalog procedure {policy_number:02d}"))
    for case_number, patient_number, policy_number, procedure in planned:
        patient_code = f"PAT-{patient_number:06d}"
        policy_code = f"POL-{policy_number:06d}"
        data.cases.append(
            AuthorizationCase(
                id=str(uuid4()),
                case_code=f"PA-{case_number:06d}",
                patient_id=patient_ids[patient_code],
                policy_id=policy_ids[policy_code],
                procedure=procedure,
                status="queued",
                created_at=SEEDED_AT,
                updated_at=SEEDED_AT,
            )
        )


def _document(
    *,
    code: str,
    patient_id: str | None,
    document_type: str,
    content: str,
    metadata: dict[str, Any],
) -> Document:
    return Document(
        id=str(uuid4()),
        document_code=code,
        patient_id=patient_id,
        document_type=document_type,
        source="catalog_sample_csv",
        content=content,
        document_metadata=metadata,
        created_at=SEEDED_AT,
        updated_at=SEEDED_AT,
    )


# Avoid the broken @property on module; export a plain callable-backed name.
def __getattr__(name: str) -> Any:
    if name == "DEMO_PROCEDURE":
        return get_demo_procedure()
    if name == "POLICY_MARKER":
        return POLICY_MARKER
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
