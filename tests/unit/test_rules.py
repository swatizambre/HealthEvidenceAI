"""Criterion status follows recorded text and does not invent citations."""

from app.services.evaluator import (
    CriterionInput,
    LabRecord,
    TextRecord,
    evaluate_criterion,
)
from app.services.safety_net import apply_safety_net, evidence_coverage, human_review_required


def _note(content: str, document_id: str = "DOC-N000001") -> TextRecord:
    return TextRecord(
        content=content,
        document_id=document_id,
        chunks=((f"{document_id}-01", content),),
        source="clinical_note",
    )


def _lab(name: str) -> LabRecord:
    content = f"{name}: synthetic-value synthetic-unit."
    return LabRecord(
        test_name=name,
        content=content,
        document_id="DOC-L000002",
        chunks=(("DOC-L000002-01", content),),
    )


def test_keyword_supported_cites_the_note() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-02",
            description="A completed course of physical therapy is documented.",
            rule={
                "type": "keyword",
                "required_any": ["completed a course of physical therapy"],
                "negation_any": ["physical therapy was not attempted"],
                "missing_label": "Completed conservative treatment",
            },
        ),
        [_note("The patient completed a course of physical therapy.")],
        [],
    )
    assert result.status == "SUPPORTED"
    assert result.evidence
    assert (
        result.evidence[0].text_reference in "The patient completed a course of physical therapy."
    )
    assert result.evidence[0].document_id == "DOC-N000001"
    assert result.evidence[0].chunk_id == "DOC-N000001-01"


def test_keyword_not_supported_cites_the_negation() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-02",
            description="A completed course of physical therapy is documented.",
            rule={
                "type": "keyword",
                "required_any": ["completed a course of physical therapy"],
                "negation_any": ["physical therapy was not attempted"],
                "missing_label": "Completed conservative treatment",
            },
        ),
        [_note("Physical therapy was not attempted.")],
        [],
    )
    assert result.status == "NOT_SUPPORTED"
    assert "not attempted" in result.evidence[0].text_reference.lower()


def test_keyword_missing_has_no_evidence() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-01",
            description="Diagnosis documented.",
            rule={
                "type": "keyword",
                "required_any": ["lumbar radiculopathy"],
                "negation_any": [],
                "missing_label": "Documented diagnosis",
            },
        ),
        [_note("Synthetic condition alpha is recorded.")],
        [],
    )
    assert result.status == "MISSING"
    assert result.evidence == []
    assert result.missing_label == "Documented diagnosis"


def test_contradictory_statements_are_unknown() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-02",
            description="A completed course of physical therapy is documented.",
            rule={
                "type": "keyword",
                "required_any": ["completed a course of physical therapy"],
                "negation_any": ["physical therapy was not attempted"],
                "missing_label": "Completed conservative treatment",
            },
        ),
        [
            _note(
                "The patient completed a course of physical therapy. "
                "Physical therapy was not attempted."
            )
        ],
        [],
    )
    assert result.status == "UNKNOWN"
    assert result.contradiction
    assert result.evidence
    combined = " ".join(item.text_reference.lower() for item in result.evidence)
    assert "completed a course of physical therapy" in combined
    assert "not attempted" in combined


def test_uncertain_statement_is_unknown() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-05",
            description="Neurologic status.",
            rule={
                "type": "statement_clarity",
                "clear_any": ["no progressive neurologic deficit"],
                "uncertain_any": ["cannot be determined"],
                "missing_label": "Clear neurologic status",
            },
        ),
        [_note("Neurologic deficit status is unclear and cannot be determined.")],
        [],
    )
    assert result.status == "UNKNOWN"
    assert result.evidence
    assert "cannot be determined" in result.evidence[0].text_reference


def test_missing_lab_is_explicit() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-04",
            description="A CBC laboratory result is present.",
            rule={
                "type": "lab_test",
                "test_name": "CBC",
                "missing_label": "Required laboratory result",
            },
        ),
        [],
        [_lab("Lipid Panel")],
    )
    assert result.status == "MISSING"
    assert result.evidence == []
    assert result.missing_label == "Required laboratory result"


def test_present_lab_without_comparator_is_unknown() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-LUMBAR-04",
            description="A CBC laboratory result is present.",
            rule={
                "type": "lab_test",
                "test_name": "CBC",
                "missing_label": "Required laboratory result",
            },
        ),
        [],
        [_lab("CBC")],
    )
    assert result.status == "UNKNOWN"
    assert result.evidence[0].source == "lab_result"


def test_lab_threshold_compares_numeric_value() -> None:
    low = LabRecord(
        test_name="HbA1c",
        content="HbA1c: 6.7 %",
        document_id="DOC-L000010",
        chunks=(("DOC-L000010-01", "HbA1c: 6.7 %"),),
        value="6.7",
        unit="%",
    )
    high = LabRecord(
        test_name="HbA1c",
        content="HbA1c: 8.1 %",
        document_id="DOC-L000011",
        chunks=(("DOC-L000011-01", "HbA1c: 8.1 %"),),
        value="8.1",
        unit="%",
    )
    rule = {
        "type": "lab_test",
        "test_name": "HbA1c",
        "comparator": ">",
        "threshold": 7.0,
        "unit": "%",
        "missing_label": "HbA1c > 7%",
    }
    below = evaluate_criterion(
        CriterionInput(code="CRIT-A1C", description="HbA1c > 7%.", rule=rule),
        [],
        [low],
    )
    assert below.status == "NOT_SUPPORTED"
    above = evaluate_criterion(
        CriterionInput(code="CRIT-A1C", description="HbA1c > 7%.", rule=rule),
        [],
        [high],
    )
    assert above.status == "SUPPORTED"


def test_lab_converts_mmol_mol_to_percent() -> None:
    # 64 mmol/mol ≈ 8.0% NGSP — should meet > 7%.
    lab = LabRecord(
        test_name="HbA1c",
        content="HbA1c: 64 mmol/mol",
        document_id="DOC-L000012",
        chunks=(("DOC-L000012-01", "HbA1c: 64 mmol/mol"),),
        value="64",
        unit="mmol/mol",
    )
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-A1C",
            description="HbA1c > 7%.",
            rule={
                "type": "lab_test",
                "test_name": "HbA1c",
                "comparator": ">",
                "threshold": 7.0,
                "unit": "%",
                "missing_label": "HbA1c > 7%",
            },
        ),
        [],
        [lab],
    )
    assert result.status == "SUPPORTED"


def test_lab_unreadable_value_is_unknown() -> None:
    lab = LabRecord(
        test_name="HbA1c",
        content="HbA1c: hemolyzed / not reported",
        document_id="DOC-L000013",
        chunks=(("DOC-L000013-01", "HbA1c: hemolyzed / not reported"),),
        value="hemolyzed",
        unit="%",
    )
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-A1C",
            description="HbA1c > 7%.",
            rule={
                "type": "lab_test",
                "test_name": "HbA1c",
                "comparator": ">",
                "threshold": 7.0,
                "unit": "%",
                "missing_label": "HbA1c > 7%",
            },
        ),
        [],
        [lab],
    )
    assert result.status == "UNKNOWN"


def test_keyword_respects_negation_cues() -> None:
    cases = [
        "Patient has no history of diabetes or hyperglycemia.",
        "Patient denies diabetes.",
        "Workup negative for diabetes.",
        "Diabetes ruled out in clinic.",
        "diabetes: none",
    ]
    for text in cases:
        result = evaluate_criterion(
            CriterionInput(
                code="CRIT-DM",
                description="Diabetes is documented.",
                rule={
                    "type": "keyword",
                    "required_any": ["diabetes"],
                    "negation_any": [],
                    "missing_label": "Diabetes documentation",
                },
            ),
            [_note(text)],
            [],
        )
        assert result.status == "MISSING", text
        assert result.evidence == []


def test_negation_is_clause_scoped() -> None:
    result = evaluate_criterion(
        CriterionInput(
            code="CRIT-DM",
            description="Diabetes is documented.",
            rule={
                "type": "keyword",
                "required_any": ["diabetes"],
                "negation_any": [],
                "missing_label": "Diabetes documentation",
            },
        ),
        [_note("No asthma. Patient has diabetes and hypertension.")],
        [],
    )
    assert result.status == "SUPPORTED"

    mixed = evaluate_criterion(
        CriterionInput(
            code="CRIT-DM",
            description="Diabetes is documented.",
            rule={
                "type": "keyword",
                "required_any": ["diabetes"],
                "negation_any": [],
                "missing_label": "Diabetes documentation",
            },
        ),
        [_note("No diabetes, but has hypertension.")],
        [],
    )
    assert mixed.status == "MISSING"


def test_unknown_rule_cannot_be_evaluated() -> None:
    result = evaluate_criterion(
        CriterionInput(code="CRIT-X", description="Mystery", rule={"type": "free_text"}),
        [_note("anything")],
        [],
    )
    assert result.status == "UNKNOWN"
    assert result.evidence == []


def test_safety_net_downgrades_uncited_support() -> None:
    from app.services.evaluator import Evaluation

    downgraded = apply_safety_net(
        [
            Evaluation(
                criterion_id="CRIT-X",
                criterion="Needs evidence",
                status="SUPPORTED",
                evidence=[],
                reason="unsupported claim",
                missing_label="Needs evidence",
            )
        ]
    )
    assert downgraded[0].status == "MISSING"
    assert downgraded[0].evidence == []
    assert human_review_required(downgraded) is True
    assert evidence_coverage(downgraded) == "NONE"
