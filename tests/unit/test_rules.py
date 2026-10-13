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


def test_lab_missing_unit_when_policy_requires_unit_is_unknown() -> None:
    # 53 mmol/mol without a unit must not be read as 53% against a %-threshold.
    lab = LabRecord(
        test_name="HbA1c",
        content="HbA1c: 53",
        document_id="DOC-L000014",
        chunks=(("DOC-L000014-01", "HbA1c: 53"),),
        value="53",
        unit="",
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
        "Family history of diabetes in mother.",
        "Rule out diabetes; awaiting HbA1c.",
        "Possible diabetes, to confirm.",
        "Diabetes was excluded after GTT.",
        "r/o diabetes pending labs",
        "diabetes?",
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


_DM_CRITERION = CriterionInput(
    code="CRIT-DM",
    description="Diabetes is documented.",
    rule={
        "type": "keyword",
        "required_any": ["diabetes"],
        "negation_any": [],
        "missing_label": "Diabetes documentation",
    },
)


def test_family_member_and_hedged_mentions_are_not_patient_evidence() -> None:
    cases = [
        # Experiencer is a relative, not the patient.
        "Mother has diabetes.",
        "FHx: diabetes (father).",
        "FH: diabetes",
        "Father with diabetes",
        "Sister diagnosed with diabetes",
        "Grandmother had diabetes.",
        "Diabetes in mother",
        "h/o diabetes in family",
        # Hedged / unconfirmed.
        "Diabetes unlikely given normal HbA1c.",
        "Diabetes (?) - to evaluate.",
        "Diabetes not confirmed",
        "Diabetes doubtful.",
        "Diabetes to be ruled out.",
        "?diabetes",
        "Evaluate for diabetes.",
    ]
    for text in cases:
        result = evaluate_criterion(_DM_CRITERION, [_note(text)], [])
        assert result.status == "MISSING", text
        assert result.evidence == [], text


def test_assertion_cues_do_not_over_negate_real_positives() -> None:
    cases = [
        "Known diabetes on metformin.",
        "Type 2 diabetes, no complications.",
        "Diabetes. No history of hypertension.",
        "Diabetes confirmed, HbA1c 8.1%; no neuropathy.",
        "Patient's diabetes is well controlled; mother has hypertension.",
        "Diabetes since 2015",
        "Mother reports patient has diabetes.",
        "Family physician documents diabetes on metformin.",
    ]
    for text in cases:
        result = evaluate_criterion(_DM_CRITERION, [_note(text)], [])
        assert result.status == "SUPPORTED", text
        assert result.evidence, text
        assert "diabetes" in result.evidence[0].text_reference.lower()


def test_keyword_matches_whole_words_and_scoped_clauses() -> None:
    expectations = {
        "Prediabetes, diet controlled.": "MISSING",
        "Likely diabetes; awaiting HbA1c.": "MISSING",
        "Denies fever, chills, or diabetes.": "MISSING",
        "Denies chest pain, has type 2 diabetes.": "SUPPORTED",
        "Lives with her mother, has diabetes on insulin.": "SUPPORTED",
        "Diabetes, uncertain type.": "SUPPORTED",
    }
    for text, status in expectations.items():
        assert evaluate_criterion(_DM_CRITERION, [_note(text)], []).status == status, text
    mi = CriterionInput(
        code="CRIT-MI",
        description="Prior MI documented.",
        rule={"type": "keyword", "required_any": ["mi"], "missing_label": "MI"},
    )
    assert evaluate_criterion(mi, [_note("Patient reports minimal back pain.")], []).status == "MISSING"


def _a1c_lab(content: str, value: str, unit: str, days_ago: float | None = None) -> LabRecord:
    from datetime import UTC, datetime, timedelta

    collected = datetime.now(UTC) - timedelta(days=days_ago) if days_ago is not None else None
    return LabRecord(
        test_name="HbA1c",
        content=content,
        document_id="DOC-L000009",
        chunks=(("DOC-L000009-01", content),),
        value=value,
        unit=unit,
        collected_at=collected,
    )


def test_lab_edge_cases_are_conservative() -> None:
    rule = {"type": "lab_test", "test_name": "HbA1c", "comparator": ">", "threshold": 7.0, "unit": "%"}
    fresh = {**rule, "max_age_days": 90}
    presence = {"type": "lab_test", "test_name": "HbA1c", "presence": True}
    cases: list[tuple[dict[str, object], LabRecord, str]] = [
        # Content-only parse must skip the "1" inside "HbA1c".
        (rule, _a1c_lab("HbA1c - 8.1%", "", ""), "SUPPORTED"),
        # 53 mmol/mol is 7.0 % at reporting precision: not > 7 %.
        (rule, _a1c_lab("HbA1c: 53 mmol/mol", "53", "mmol/mol"), "NOT_SUPPORTED"),
        ({**rule, "comparator": ">="}, _a1c_lab("HbA1c: 53 mmol/mol", "53", "mmol/mol"), "SUPPORTED"),
        # Censored values cannot be compared to a threshold.
        (rule, _a1c_lab("HbA1c: <7.5 %", "<7.5", "%"), "UNKNOWN"),
        # Recency required: stale, undated, and fresh results.
        (fresh, _a1c_lab("HbA1c: 8.1 %", "8.1", "%", days_ago=400), "UNKNOWN"),
        (fresh, _a1c_lab("HbA1c: 8.1 %", "8.1", "%"), "UNKNOWN"),
        (fresh, _a1c_lab("HbA1c: 8.1 %", "8.1", "%", days_ago=10), "SUPPORTED"),
        # A row with no reportable result is not "present".
        (presence, _a1c_lab("HbA1c: pending", "pending", ""), "UNKNOWN"),
        (presence, _a1c_lab("HbA1c: 6.2 %", "6.2", "%"), "SUPPORTED"),
    ]
    for lab_rule, lab, status in cases:
        result = evaluate_criterion(
            CriterionInput(code="CRIT-A1C", description="HbA1c > 7%", rule=dict(lab_rule)),
            [],
            [lab],
        )
        assert result.status == status, (lab_rule, lab.content)


def test_find_affirmed_phrase_is_public_alias() -> None:
    from app.services.evaluator import find_affirmed_phrase

    assert find_affirmed_phrase("Known diabetes on metformin.", ["diabetes"]) == "diabetes"
    assert find_affirmed_phrase("Mother has diabetes.", ["diabetes"]) is None
    assert find_affirmed_phrase("", ["diabetes"]) is None


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
