"""Lexical citation verification for SUPPORTED checklist items."""

from __future__ import annotations

from typing import Any

from app.services.citation_check import (
    DOWNGRADE_REASON,
    ChunkText,
    chunk_texts_from_hits,
    cited_chunk_ids,
    criterion_phrases,
    span_supports,
    verify_citations,
)
from app.services.evaluator import (
    CriterionInput,
    LabRecord,
    TextRecord,
    evaluate_criterion,
)

_DM_RULE = {"type": "keyword", "required_any": ["diabetes"], "negation_any": []}
_DM_CRITERIA = [{"criterion_id": "CRIT-DM", "description": "Diabetes is documented.", "rule": _DM_RULE}]


def _supported(chunk_id: str, document_id: str = "DOC-1") -> dict[str, Any]:
    return {
        "criterion_id": "CRIT-DM",
        "criterion": "Diabetes is documented.",
        "status": "SUPPORTED",
        "evidence": [
            {
                "document_id": document_id,
                "chunk_id": chunk_id,
                "source": "clinical_note",
                "text_reference": "model quoted text",
            }
        ],
        "reason": "AI check: documented.",
    }


def test_rules_path_citations_always_pass() -> None:
    """Rules citations come from _cite_text and always contain the affirmed phrase."""
    texts = [
        "Known diabetes on metformin.",
        "No diabetes in 2010. Patient now has diabetes on metformin.",
        "Mother has diabetes.\nPatient has diabetes since 2015.",
    ]
    for text in texts:
        result = evaluate_criterion(
            CriterionInput("CRIT-DM", "Diabetes is documented.", _DM_RULE),
            [TextRecord(text, "DOC-1", (("DOC-1-01", text),), "clinical_note")],
            [],
        )
        assert result.status == "SUPPORTED", text
        assert "diabetes" in result.evidence[0].text_reference.lower()
        rows = [
            {
                "criterion_id": "CRIT-DM",
                "status": result.status,
                "evidence": [
                    {"document_id": ev.document_id, "chunk_id": ev.chunk_id}
                    for ev in result.evidence
                ],
            }
        ]
        check = verify_citations(rows, _DM_CRITERIA, {"DOC-1-01": ChunkText("DOC-1", text)})
        assert check.passed == 1 and not check.downgraded, text


def test_lab_citation_passes_on_test_name() -> None:
    rule = {"type": "lab_test", "test_name": "HbA1c", "comparator": ">", "threshold": 7, "unit": "%"}
    lab = LabRecord("HbA1c", "HbA1c: 8.1 %", "LAB-1", (("LAB-1-01", "HbA1c: 8.1 %"),), "8.1", "%")
    result = evaluate_criterion(CriterionInput("CRIT-A1C", "HbA1c > 7%", rule), [], [lab])
    assert result.status == "SUPPORTED"
    rows = [
        {
            "criterion_id": "CRIT-A1C",
            "status": "SUPPORTED",
            "evidence": [{"document_id": "LAB-1", "chunk_id": "LAB-1-01"}],
        }
    ]
    criteria = [{"criterion_id": "CRIT-A1C", "description": "HbA1c > 7%", "rule": rule}]
    check = verify_citations(rows, criteria, {"LAB-1-01": ChunkText("LAB-1", "HbA1c: 8.1 %")})
    assert check.passed == 1


def test_family_history_citation_is_downgraded() -> None:
    check = verify_citations(
        [_supported("CHK-1")],
        _DM_CRITERIA,
        {"CHK-1": ChunkText("DOC-1", "Mother has diabetes.")},
    )
    item = check.criterion_results[0]
    assert item["status"] == "UNKNOWN"
    assert item["reason"] == DOWNGRADE_REASON
    # Citation resolves to real stored text, so the reviewer still sees it.
    assert item["evidence"]
    assert check.downgraded == ["CRIT-DM"]
    assert check.notes and "did not support" in check.notes[0]


def test_unresolved_citation_is_downgraded_and_dropped() -> None:
    check = verify_citations([_supported("CHK-404")], _DM_CRITERIA, {})
    item = check.criterion_results[0]
    assert item["status"] == "UNKNOWN"
    assert item["evidence"] == []
    assert check.unresolved_citations == 1


def test_citation_from_other_document_does_not_resolve() -> None:
    check = verify_citations(
        [_supported("CHK-1", document_id="DOC-OTHER")],
        _DM_CRITERIA,
        {"CHK-1": ChunkText("DOC-1", "Known diabetes on metformin.")},
    )
    assert check.criterion_results[0]["status"] == "UNKNOWN"


def test_one_good_citation_is_enough() -> None:
    row = _supported("CHK-1")
    row["evidence"].append({"document_id": "DOC-2", "chunk_id": "CHK-2"})
    check = verify_citations(
        [row],
        _DM_CRITERIA,
        {
            "CHK-1": ChunkText("DOC-1", "BMI 31."),
            "CHK-2": ChunkText("DOC-2", "Type 2 diabetes, no complications."),
        },
    )
    assert check.criterion_results[0]["status"] == "SUPPORTED"
    assert check.passed == 1


def test_non_supported_rows_are_untouched() -> None:
    rows = [
        {"criterion_id": "CRIT-DM", "status": "MISSING", "evidence": []},
        {"criterion_id": "CRIT-DM", "status": "NOT_SUPPORTED", "evidence": [{"chunk_id": "X"}]},
    ]
    check = verify_citations(rows, _DM_CRITERIA, {})
    assert [r["status"] for r in check.criterion_results] == ["MISSING", "NOT_SUPPORTED"]
    assert check.checked == 0


def test_llm_criterion_without_phrases_uses_shared_tokens() -> None:
    desc = "Failed conservative therapy for six weeks"
    assert span_supports(
        "Failed conservative therapy with physical therapy for 12 weeks.",
        phrases=[],
        description=desc,
    )
    assert not span_supports("BMI 31 recorded today.", phrases=[], description=desc)
    assert not span_supports("Weeks of rest only.", phrases=[], description=desc)
    assert not span_supports("No conservative therapy attempted.", phrases=[], description=desc)


def test_criterion_phrases_by_rule_type() -> None:
    assert criterion_phrases({"type": "keyword", "required_any": ["a", " "]}) == ["a"]
    assert criterion_phrases({"type": "statement_clarity", "clear_any": ["b"]}) == ["b"]
    assert criterion_phrases({"type": "lab_test", "test_name": "HbA1c"}) == ["HbA1c"]
    assert criterion_phrases({"type": "free_text"}) == []
    assert criterion_phrases(None) == []


def test_hit_index_and_cited_ids() -> None:
    hits = [
        {"chunk_id": "C1", "document_id": "D1", "content": "text"},
        {"chunk_id": "", "document_id": "D2", "content": "skip"},
        {"chunk_id": "C1", "document_id": "D9", "content": "dup"},
    ]
    index = chunk_texts_from_hits(hits)
    assert index == {"C1": ChunkText("D1", "text")}
    assert cited_chunk_ids([_supported("C7"), {"status": "MISSING", "evidence": [{"chunk_id": "C8"}]}]) == {
        "C7"
    }
    assert "downgraded=0" in verify_citations([], [], {}).summary()


def test_every_gold_rules_citation_passes_the_verifier() -> None:
    """Rules-path SUPPORTED citations must never be downgraded by the lexical verifier."""
    import json
    from pathlib import Path

    from evaluation.run_gold import GOLD_PATH, _lab, _note

    cases = json.loads(Path(GOLD_PATH).read_text(encoding="utf-8"))["cases"]
    checked = 0
    for case in cases:
        notes = [_note(text, i) for i, text in enumerate(case.get("notes") or [], start=1)]
        labs = [_lab(raw, i) for i, raw in enumerate(case.get("labs") or [], start=1)]
        raw = case["criterion"]
        result = evaluate_criterion(
            CriterionInput(raw["code"], raw["description"], dict(raw["rule"])), notes, labs
        )
        if result.status != "SUPPORTED":
            continue
        chunks: dict[str, ChunkText] = {}
        for record in [*notes, *labs]:
            for code, text in record.chunks:
                chunks[code] = ChunkText(record.document_id, text)
        rows = [
            {
                "criterion_id": raw["code"],
                "status": "SUPPORTED",
                "evidence": [
                    {"document_id": ev.document_id, "chunk_id": ev.chunk_id} for ev in result.evidence
                ],
            }
        ]
        spec = [{"criterion_id": raw["code"], "description": raw["description"], "rule": raw["rule"]}]
        check = verify_citations(rows, spec, chunks)
        assert not check.downgraded, case["id"]
        checked += 1
    assert checked >= 15
