"""Gold-set harness smoke: metrics + rules path gate."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation.metrics import CaseOutcome, gate_ok, summarize_outcomes
from evaluation.run_gold import GOLD_PATH
from evaluation.run_gold import main as run_gold_main


def test_false_supported_metric() -> None:
    outcomes = [
        CaseOutcome("a", "MISSING", "SUPPORTED", 1, 1.0, "rules"),
        CaseOutcome("b", "MISSING", "MISSING", 0, 1.0, "rules"),
        CaseOutcome("c", "SUPPORTED", "SUPPORTED", 1, 1.0, "rules"),
    ]
    report = summarize_outcomes("rules", outcomes)
    assert report.false_supported_count == 1
    # Denominator is cases whose gold is not SUPPORTED (a, b), not all cases.
    assert report.false_supported_rate == 1 / 2
    assert report.missing_recall == 0.5
    assert report.supported_recall == 1.0


def test_supported_recall_and_confusion() -> None:
    outcomes = [
        CaseOutcome("a", "SUPPORTED", "SUPPORTED", 1, 1.0, "rules"),
        CaseOutcome("b", "SUPPORTED", "MISSING", 0, 1.0, "rules"),
        CaseOutcome("c", "NOT_SUPPORTED", "NOT_SUPPORTED", 1, 1.0, "rules"),
        CaseOutcome("d", "UNKNOWN", "SUPPORTED", 0, 1.0, "rules"),
    ]
    report = summarize_outcomes("rules", outcomes)
    assert report.supported_recall == 0.5
    assert report.false_supported_rate == 1 / 2
    assert report.confusion["SUPPORTED"]["MISSING"] == 1
    assert report.confusion["UNKNOWN"]["SUPPORTED"] == 1
    assert report.confusion["NOT_SUPPORTED"]["NOT_SUPPORTED"] == 1
    # Citation presence: 1 of 2 SUPPORTED predictions carries a citation.
    assert report.citation_presence == 0.5
    assert report.citation_precision == report.citation_presence
    payload = report.as_dict()
    assert payload["gold_counts"] == {
        "SUPPORTED": 2,
        "NOT_SUPPORTED": 1,
        "MISSING": 0,
        "UNKNOWN": 1,
    }
    assert "citation_presence" in payload and "citation_precision" not in payload
    ok, reasons = gate_ok(report, min_cases=1)
    assert not ok
    assert any("supported_recall" in r for r in reasons)
    assert any("citation_presence" in r for r in reasons)


def test_all_supported_set_has_zero_false_supported_rate() -> None:
    report = summarize_outcomes("rules", [CaseOutcome("a", "SUPPORTED", "SUPPORTED", 1, 1.0, "rules")])
    assert report.false_supported_rate == 0.0


def test_gold_rules_path_passes_gate() -> None:
    assert run_gold_main(["--path", "rules"]) == 0


def test_gold_writes_result_file(tmp_path: Path) -> None:
    out = tmp_path / "gate" / "gold.json"
    assert run_gold_main(["--path", "rules", "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["passed"] is True
    assert result["path"] == "rules"
    assert "false_supported_rate" in result["metrics"]

def test_old_citation_flag_is_accepted() -> None:
    assert run_gold_main(["--path", "rules", "--min-citation-precision", "0.95"]) == 0


def test_gold_set_is_balanced() -> None:
    payload = json.loads(Path(GOLD_PATH).read_text(encoding="utf-8"))
    assert payload["status"] == "engineering_seed"
    cases = payload["cases"]
    assert len(cases) >= 60
    assert len({case["id"] for case in cases}) == len(cases)
    counts = Counter(case["expected_status"] for case in cases)
    assert counts["SUPPORTED"] >= 15
    assert counts["NOT_SUPPORTED"] >= 6
    assert counts["UNKNOWN"] >= 8
    assert counts["MISSING"] >= 15
    notes = {note for case in cases for note in case.get("notes") or []}
    for sentence in (
        "Mother has diabetes.",
        "FHx: diabetes (father).",
        "Diabetes unlikely given normal HbA1c.",
        "?diabetes",
        "Known diabetes on metformin.",
        "Diabetes since 2015",
    ):
        assert sentence in notes


def test_gate_rejects_false_supported() -> None:
    outcomes = [
        CaseOutcome(f"c{i}", "MISSING", "SUPPORTED", 1, 1.0, "rules") for i in range(25)
    ]
    report = summarize_outcomes("rules", outcomes)
    ok, reasons = gate_ok(report, max_false_supported_rate=0.0, min_cases=20)
    assert not ok
    assert any("false_supported" in r for r in reasons)
