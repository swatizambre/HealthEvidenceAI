"""Gold-set evaluation gate (clinical-safety metrics).

Tracks false-SUPPORTED rate, MISSING recall, citation precision, and latency.
Run separately per path (rules today; model paths when configured).

  uv run python -m evaluation.run_gold
  uv run python -m evaluation.run_gold --path rules
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.services.evaluator import (
    CriterionInput,
    LabRecord,
    TextRecord,
    evaluate_criterion,
)
from app.services.safety_net import apply_safety_net

from evaluation.metrics import CaseOutcome, gate_ok, summarize_outcomes

ROOT = Path(__file__).resolve().parent
GOLD_PATH = ROOT / "gold" / "criteria_cases.v1.json"


def _note(content: str, index: int) -> TextRecord:
    doc = f"DOC-GOLD-{index:04d}"
    return TextRecord(
        content=content,
        document_id=doc,
        chunks=((f"{doc}-01", content),),
        source="clinical_note",
    )


def _lab(raw: dict, index: int) -> LabRecord:
    doc = f"DOC-GOLD-LAB-{index:04d}"
    content = str(raw.get("content") or "")
    return LabRecord(
        test_name=str(raw.get("test_name") or "lab"),
        content=content,
        document_id=doc,
        chunks=((f"{doc}-01", content),),
        value=str(raw.get("value") or ""),
        unit=str(raw.get("unit") or ""),
    )


def _run_case(case: dict) -> CaseOutcome:
    notes = [_note(text, i) for i, text in enumerate(case.get("notes") or [], start=1)]
    labs = [_lab(item, i) for i, item in enumerate(case.get("labs") or [], start=1)]
    criterion_raw = case["criterion"]
    criterion = CriterionInput(
        code=str(criterion_raw["code"]),
        description=str(criterion_raw["description"]),
        rule=dict(criterion_raw["rule"]),
    )
    started = time.perf_counter()
    result = evaluate_criterion(criterion, notes, labs)
    result = apply_safety_net([result])[0]
    latency_ms = (time.perf_counter() - started) * 1000.0
    expected = str(case["expected_status"]).upper()
    predicted = str(result.status).upper()
    min_citations = int(case.get("min_citations") or 0)
    cite_ok = len(result.evidence) >= min_citations
    status_ok = predicted == expected
    ok = status_ok and cite_ok
    detail = ""
    if not status_ok:
        detail = f"expected={expected} predicted={predicted}"
    elif not cite_ok:
        detail = f"citations={len(result.evidence)} min={min_citations}"
    return CaseOutcome(
        case_id=str(case["id"]),
        expected=expected,
        predicted=predicted,
        citation_count=len(result.evidence),
        latency_ms=latency_ms,
        path=str(case.get("path") or "rules"),
        tags=list(case.get("tags") or []),
        ok=ok,
        detail=detail,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gold-set clinical-safety evaluation")
    parser.add_argument("--path", default="rules", help="Scoring path to evaluate")
    parser.add_argument(
        "--cases",
        type=Path,
        default=GOLD_PATH,
        help="Path to criteria gold JSON",
    )
    parser.add_argument(
        "--max-false-supported",
        type=float,
        default=0.0,
        help="Release gate: max false-SUPPORTED rate",
    )
    parser.add_argument(
        "--min-missing-recall",
        type=float,
        default=0.85,
    )
    parser.add_argument(
        "--min-citation-precision",
        type=float,
        default=0.95,
    )
    parser.add_argument(
        "--max-latency-p95-ms",
        type=float,
        default=500.0,
    )
    parser.add_argument("--min-cases", type=int, default=20)
    args = parser.parse_args(argv)

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = [
        case
        for case in payload.get("cases") or []
        if str(case.get("path") or "rules") == args.path
        and case.get("active", True) is not False
    ]
    if not cases:
        print(f"FAIL no cases for path={args.path}")
        return 1

    outcomes = [_run_case(case) for case in cases]
    report = summarize_outcomes(args.path, outcomes)
    print("Gold evaluation (clinical-safety metrics)")
    print(f"dataset={payload.get('version')} status={payload.get('status')}")
    print(json.dumps(report.as_dict(), indent=2))
    failed = [o for o in outcomes if not o.ok]
    for item in failed[:20]:
        print(f"FAIL {item.case_id} {item.detail}")
    if len(failed) > 20:
        print(f"... and {len(failed) - 20} more case failures")

    passed_gate, reasons = gate_ok(
        report,
        max_false_supported_rate=args.max_false_supported,
        min_missing_recall=args.min_missing_recall,
        min_citation_precision=args.min_citation_precision,
        max_latency_p95_ms=args.max_latency_p95_ms,
        min_cases=args.min_cases,
    )
    # Exact case failures also fail the gate (engineering seed must be green).
    if failed:
        passed_gate = False
        reasons.append(f"case_failures={len(failed)}")
    if passed_gate:
        print(f"GATE PASS path={args.path}")
        return 0
    print(f"GATE FAIL path={args.path} reasons={reasons}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
