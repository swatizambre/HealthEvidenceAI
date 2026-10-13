"""Gold-set harness smoke: metrics + rules path gate."""

from __future__ import annotations

from evaluation.metrics import CaseOutcome, gate_ok, summarize_outcomes
from evaluation.run_gold import main as run_gold_main


def test_false_supported_metric() -> None:
    outcomes = [
        CaseOutcome("a", "MISSING", "SUPPORTED", 1, 1.0, "rules"),
        CaseOutcome("b", "MISSING", "MISSING", 0, 1.0, "rules"),
        CaseOutcome("c", "SUPPORTED", "SUPPORTED", 1, 1.0, "rules"),
    ]
    report = summarize_outcomes("rules", outcomes)
    assert report.false_supported_count == 1
    assert report.false_supported_rate == 1 / 3
    assert report.missing_recall == 0.5


def test_gold_rules_path_passes_gate() -> None:
    assert run_gold_main(["--path", "rules"]) == 0


def test_gate_rejects_false_supported() -> None:
    outcomes = [
        CaseOutcome(f"c{i}", "MISSING", "SUPPORTED", 1, 1.0, "rules") for i in range(25)
    ]
    report = summarize_outcomes("rules", outcomes)
    ok, reasons = gate_ok(report, max_false_supported_rate=0.0, min_cases=20)
    assert not ok
    assert any("false_supported" in r for r in reasons)
