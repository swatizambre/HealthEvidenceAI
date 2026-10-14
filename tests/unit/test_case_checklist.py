"""One readiness computation for desk worklist, workspace, prepare and Reviews."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import AuthorizationCase
from app.services.case_checklist import (
    ChecklistItem,
    clinical_results,
    form_items,
    normalize_results,
    readiness_from_results,
    summarize_readiness,
)


def _item(status: str, *, required: bool = True, group: str = "clinical") -> ChecklistItem:
    return ChecklistItem(item_id=f"x-{status}", group=group, label=status, status=status,
                         required=required)


def test_readiness_is_supported_over_required_only() -> None:
    items = [
        *[_item("SUPPORTED") for _ in range(8)],
        _item("MISSING"),
        _item("UNKNOWN"),
        _item("MISSING", required=False),
    ]
    summary = summarize_readiness(items)
    assert summary.required == 10
    assert summary.supported == 8
    assert summary.percent == 80
    assert summary.missing == 1
    assert summary.unknown == 1
    assert summary.not_supported == 0
    assert summary.label.startswith("1 item missing")
    assert summary.open_items == 2
    assert summary.as_dict()["percent"] == 80


def test_readiness_labels() -> None:
    assert summarize_readiness([_item("SUPPORTED")]).label == "All required items supported"
    assert summarize_readiness([]).percent == 0
    two = summarize_readiness([_item("MISSING"), _item("MISSING"), _item("NOT_SUPPORTED")])
    assert two.label == "2 items missing · 1 not supported"
    assert two.percent == 0


def test_results_normalize_and_filter_social_noise() -> None:
    rows = normalize_results(
        [
            {"criterion_id": "C1", "criterion": "Hemoglobin result is present.",
             "status": "supported", "evidence": [{"document_id": "DOC-1", "chunk_id": "DOC-1-01",
                                                  "source": "lab_result",
                                                  "text_reference": "Hb 12"}]},
            {"criterion_id": "C2", "criterion": "Full-time employment (finding) is documented.",
             "status": "MISSING"},
            {"criterion_id": "C3", "criterion": "Odd", "status": "WEIRD"},
        ]
    )
    assert rows[0]["status"] == "SUPPORTED"
    assert rows[2]["status"] == "UNKNOWN"
    kept = clinical_results(rows)
    assert [row["criterion_id"] for row in kept] == ["C1", "C3"]
    # Same numbers as the legacy packet computation (supported / filtered criteria).
    assert readiness_from_results(rows).percent == 50


def test_form_items_only_for_desk_cases() -> None:
    legacy = AuthorizationCase(case_code="PA-999999", procedure="x")
    assert form_items(legacy) == []
    desk = AuthorizationCase(
        case_code="PA-999998",
        procedure="Phacoemulsification with IOL",
        payer_type="tpa",
        insurer_name="Star Health (synthetic)",
        tpa_name="",
        policy_number="SH-2026-0001234",
        admission_type="planned",
        admitted_at=datetime(2026, 10, 14, 8, tzinfo=UTC),
        treating_doctor="Dr. R. Joshi",
        provisional_diagnosis="Senile cataract right eye",
        icd10_code="",
        proposed_treatment="Phacoemulsification with IOL",
        estimated_cost_inr=32000,
    )
    items = {item.item_id: item for item in form_items(desk)}
    assert items["form:payer"].status == "MISSING"  # TPA case without TPA name
    assert items["form:diagnosis_icd10"].status == "MISSING"
    assert "ICD-10" in items["form:diagnosis_icd10"].reason
    assert items["form:policy_number"].status == "SUPPORTED"
    assert items["form:cost_estimate"].status == "SUPPORTED"
    assert all(item.group == "form" and item.required for item in items.values())
