"""Build an evidence-review policy from whatever facts are present in a catalog.

Criteria are chosen from observed conditions and labs. They are not hard-coded to
one Synthea release. The resulting checklist is still a prototype evidence review,
not a clinical or coverage decision.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.evaluator import (
    STATUS_MISSING,
    STATUS_NOT_SUPPORTED,
    STATUS_SUPPORTED,
    STATUS_UNKNOWN,
    CriterionInput,
    LabRecord,
    TextRecord,
    evaluate_criteria,
)
from app.services.synthea_source import SyntheaCatalog, SyntheaPatient

POLICY_MARKER = "POLICY_MARKER_DYNAMIC_REVIEW"


@dataclass(frozen=True)
class DynamicPolicy:
    title: str
    procedure: str
    content: str
    marker: str
    criteria: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CaseProfiles:
    missing_lab: SyntheaPatient
    complete: SyntheaPatient
    not_supported: SyntheaPatient
    contradicted: SyntheaPatient


def build_dynamic_policy(catalog: SyntheaCatalog) -> DynamicPolicy:
    """Discover criteria that admit the four deterministic demo profiles."""
    condition_counts: Counter[str] = Counter()
    lab_counts: Counter[str] = Counter()
    for patient in catalog.patients:
        condition_counts.update(set(patient.conditions))
        lab_counts.update({lab.description for lab in patient.labs})
    if not condition_counts or not lab_counts:
        raise RuntimeError("The catalog has no conditions or laboratory facts to build a policy.")

    from app.services.disorders import is_clinical_condition

    # Prefer clinical disorders so demo checklists are not social/admin noise.
    clinical_counts = Counter(
        {name: count for name, count in condition_counts.items() if is_clinical_condition(name)}
    )
    baselines = [name for name, _ in (clinical_counts or condition_counts).most_common(12)]
    labs = [name for name, count in lab_counts.most_common() if 0 < count < len(catalog.patients)]
    opposing_pairs = [
        pair
        for pair in _opposing_pairs(catalog.patients)
        if is_clinical_condition(pair[0]) and is_clinical_condition(pair[1])
    ] or _opposing_pairs(catalog.patients)
    clarity_pairs = [
        pair
        for pair in _clarity_pairs(catalog.patients)
        if is_clinical_condition(pair[0]) and is_clinical_condition(pair[1])
    ] or _clarity_pairs(catalog.patients)

    for baseline in baselines:
        for support in baselines:
            if support == baseline:
                continue
            for left, right in opposing_pairs:
                if left in {baseline, support} or right in {baseline, support}:
                    continue
                for clear_phrase, uncertain_phrase in clarity_pairs:
                    if len({baseline, support, left, right, clear_phrase, uncertain_phrase}) < 6:
                        continue
                    for rare_lab in labs[:8]:
                        criteria = _criteria(
                            baseline=baseline,
                            support=support,
                            opposing=(left, right),
                            rare_lab=rare_lab,
                            clear_phrase=clear_phrase,
                            uncertain_phrase=uncertain_phrase,
                        )
                        try:
                            select_case_profiles(
                                catalog,
                                DynamicPolicy("", "", "", POLICY_MARKER, tuple(criteria)),
                            )
                        except RuntimeError:
                            continue
                        content = _content(
                            baseline=baseline,
                            support=support,
                            opposing=(left, right),
                            rare_lab=rare_lab,
                            common_lab=lab_counts.most_common(1)[0][0],
                            clear_phrase=clear_phrase,
                            uncertain_phrase=uncertain_phrase,
                        )
                        return DynamicPolicy(
                            title="Prior authorization evidence checklist",
                            procedure=_preferred_procedure(catalog.patients),
                            content=content,
                            marker=POLICY_MARKER,
                            criteria=tuple(criteria),
                        )
    raise RuntimeError(
        "Could not derive a catalog policy that supports missing, complete, "
        "not-supported, and contradicted demo profiles."
    )


def select_case_profiles(catalog: SyntheaCatalog, policy: DynamicPolicy) -> CaseProfiles:
    """Pick patients by evaluating the same rules the API will use."""
    inputs = [
        CriterionInput(code=str(item["code"]), description=str(item["description"]), rule=dict(item["rule"]))
        for item in policy.criteria
    ]
    missing_lab = _first_match(catalog.patients, inputs, _is_missing_lab_profile)
    used = {missing_lab.source_id}
    complete = _first_match(
        catalog.patients,
        inputs,
        lambda statuses: all(status == STATUS_SUPPORTED for status in statuses.values()),
        exclude=used,
    )
    used.add(complete.source_id)
    not_supported = _first_match(
        catalog.patients,
        inputs,
        lambda statuses: statuses.get("CRIT-DYN-02") == STATUS_NOT_SUPPORTED,
        exclude=used,
    )
    used.add(not_supported.source_id)
    contradicted = _first_match(
        catalog.patients,
        inputs,
        lambda statuses: statuses.get("CRIT-DYN-02") == STATUS_UNKNOWN,
        exclude=used,
    )
    return CaseProfiles(
        missing_lab=missing_lab,
        complete=complete,
        not_supported=not_supported,
        contradicted=contradicted,
    )


def evaluate_patient_statuses(
    patient: SyntheaPatient,
    criteria: list[CriterionInput],
) -> dict[str, str]:
    notes, labs = _records_for_patient(patient)
    return {item.criterion_id: item.status for item in evaluate_criteria(criteria, notes, labs)}


def _is_missing_lab_profile(statuses: dict[str, str]) -> bool:
    return (
        statuses.get("CRIT-DYN-01") == STATUS_SUPPORTED
        and statuses.get("CRIT-DYN-02") == STATUS_SUPPORTED
        and statuses.get("CRIT-DYN-03") == STATUS_SUPPORTED
        and statuses.get("CRIT-DYN-04") == STATUS_MISSING
        and statuses.get("CRIT-DYN-05") == STATUS_UNKNOWN
    )


def _first_match(
    patients: tuple[SyntheaPatient, ...],
    criteria: list[CriterionInput],
    predicate: Callable[[dict[str, str]], bool],
    exclude: set[str] | None = None,
) -> SyntheaPatient:
    blocked = exclude or set()
    for patient in patients:
        if patient.source_id in blocked:
            continue
        statuses = evaluate_patient_statuses(patient, criteria)
        if predicate(statuses):
            return patient
    raise RuntimeError(
        "No patient in the loaded catalog matches a required evidence-review profile."
    )


def _records_for_patient(patient: SyntheaPatient) -> tuple[list[TextRecord], list[LabRecord]]:
    med = patient.medications[0].description if patient.medications else "none recorded"
    note = "\n".join(
        [
            f"Source patient {patient.source_id}.",
            "Assessment:",
            *[f"The clinical record documents {item}." for item in patient.conditions],
            "Current medication:",
            f"The patient is recorded as taking {med}.",
        ]
    )
    notes = [
        TextRecord(
            content=note,
            document_id=f"TMP-N-{patient.source_id}",
            chunks=((f"TMP-N-{patient.source_id}-01", note),),
            source="clinical_note",
        )
    ]
    labs = [
        LabRecord(
            test_name=lab.description,
            content=content,
            document_id=f"TMP-L-{patient.source_id}-{index}",
            chunks=((f"TMP-L-{patient.source_id}-{index:02d}", content),),
        )
        for index, lab in enumerate(patient.labs, start=1)
        for content in [f"{lab.description}: {lab.value} {lab.unit}".strip()]
    ]
    return notes, labs


def _criteria(
    *,
    baseline: str,
    support: str,
    opposing: tuple[str, str],
    rare_lab: str,
    clear_phrase: str,
    uncertain_phrase: str,
) -> list[dict[str, Any]]:
    return [
        {
            "code": "CRIT-DYN-01",
            "description": f"{baseline} is documented.",
            "rule": {
                "type": "keyword",
                "required_any": [baseline],
                "negation_any": [],
                "missing_label": "Required documented finding",
            },
        },
        {
            "code": "CRIT-DYN-02",
            "description": f"{opposing[0]} is documented.",
            "rule": {
                "type": "keyword",
                "required_any": [opposing[0]],
                "negation_any": [opposing[1]],
                "missing_label": "Required affirmative finding",
            },
        },
        {
            "code": "CRIT-DYN-03",
            "description": f"{support} is documented.",
            "rule": {
                "type": "keyword",
                "required_any": [support],
                "negation_any": [],
                "missing_label": "Secondary documented finding",
            },
        },
        {
            "code": "CRIT-DYN-04",
            "description": f"A {rare_lab} result is present.",
            "rule": {
                "type": "lab_test",
                "test_name": rare_lab,
                "presence": True,
                "missing_label": "Required laboratory result",
            },
        },
        {
            "code": "CRIT-DYN-05",
            "description": f"The record clearly documents {clear_phrase}.",
            "rule": {
                "type": "statement_clarity",
                "clear_any": [clear_phrase],
                "uncertain_any": [uncertain_phrase],
                "missing_label": "Clear status statement",
            },
        },
    ]


def _content(
    *,
    baseline: str,
    support: str,
    opposing: tuple[str, str],
    rare_lab: str,
    common_lab: str,
    clear_phrase: str,
    uncertain_phrase: str,
) -> str:
    return (
        "Evidence review policy POL-000001.\n"
        "Criteria were derived from facts present in the loaded synthetic catalog.\n"
        "This checklist is a prototype evidence review. It is not a coverage determination "
        "and not a clinical decision.\n"
        f"{POLICY_MARKER}\n"
        f"Baseline finding: {baseline}.\n"
        f"Affirmative finding: {opposing[0]}. Opposing finding: {opposing[1]}.\n"
        f"Secondary finding: {support}.\n"
        f"Required laboratory result: {rare_lab}. Common laboratory in sample: {common_lab}.\n"
        f"Clear statement: {clear_phrase}. Uncertain statement: {uncertain_phrase}.\n"
    )


def _opposing_pairs(patients: tuple[SyntheaPatient, ...]) -> list[tuple[str, str]]:
    condition_sets = [set(patient.conditions) for patient in patients]
    universe = sorted({item for group in condition_sets for item in group})
    scored: list[tuple[int, str, str]] = []
    for left in universe:
        for right in universe:
            if left >= right:
                continue
            only_left = sum(1 for group in condition_sets if left in group and right not in group)
            only_right = sum(1 for group in condition_sets if right in group and left not in group)
            both = sum(1 for group in condition_sets if left in group and right in group)
            if only_left and only_right and both:
                scored.append((min(only_left, only_right, both), left, right))
    scored.sort(reverse=True)
    return [(left, right) for _, left, right in scored[:40]]


def _clarity_pairs(patients: tuple[SyntheaPatient, ...]) -> list[tuple[str, str]]:
    counts: Counter[str] = Counter()
    for patient in patients:
        counts.update(set(patient.conditions))
    ordered = [name for name, _ in counts.most_common()]
    pairs: list[tuple[str, str]] = []
    for left in ordered[:20]:
        for right in ordered[:20]:
            if left == right:
                continue
            has_clear_only = any(
                left in patient.conditions and right not in patient.conditions for patient in patients
            )
            has_uncertain_only = any(
                right in patient.conditions and left not in patient.conditions for patient in patients
            )
            if has_clear_only and has_uncertain_only:
                pairs.append((left, right))
    return pairs[:40]


def _preferred_procedure(patients: tuple[SyntheaPatient, ...]) -> str:
    """Pick a demo PA procedure — skip Synthea admin noise like medication reconciliation."""
    from app.services.disorders import is_clinical_procedure

    counts: Counter[str] = Counter()
    for patient in patients:
        for procedure in patient.procedures:
            name = (procedure.description or "").strip()
            if name and is_clinical_procedure(name):
                counts[name] += 1
    if counts:
        return counts.most_common(1)[0][0]
    return "Imaging evidence review"
