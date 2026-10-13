"""Clinical-safety metrics for criterion-level gold evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

STATUS_SUPPORTED = "SUPPORTED"
STATUS_MISSING = "MISSING"
STATUS_NOT_SUPPORTED = "NOT_SUPPORTED"
STATUS_UNKNOWN = "UNKNOWN"


@dataclass
class CaseOutcome:
    case_id: str
    expected: str
    predicted: str
    citation_count: int
    latency_ms: float
    path: str
    tags: list[str] = field(default_factory=list)
    ok: bool = False
    detail: str = ""


@dataclass
class GoldReport:
    path: str
    outcomes: list[CaseOutcome]
    false_supported_rate: float
    false_supported_count: int
    missing_recall: float
    citation_precision: float
    latency_p50_ms: float
    latency_p95_ms: float
    exact_match_rate: float
    n: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "n": self.n,
            "false_supported_rate": round(self.false_supported_rate, 4),
            "false_supported_count": self.false_supported_count,
            "missing_recall": round(self.missing_recall, 4),
            "citation_precision": round(self.citation_precision, 4),
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "exact_match_rate": round(self.exact_match_rate, 4),
        }


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * p
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    weight = rank - low
    return sorted_vals[low] * (1 - weight) + sorted_vals[high] * weight


def summarize_outcomes(path: str, outcomes: list[CaseOutcome]) -> GoldReport:
    n = len(outcomes)
    false_supported = [
        o
        for o in outcomes
        if o.predicted == STATUS_SUPPORTED and o.expected != STATUS_SUPPORTED
    ]
    gold_missing = [o for o in outcomes if o.expected == STATUS_MISSING]
    pred_missing_ok = [o for o in gold_missing if o.predicted == STATUS_MISSING]
    supported_preds = [o for o in outcomes if o.predicted == STATUS_SUPPORTED]
    cited_ok = [o for o in supported_preds if o.citation_count > 0]
    latencies = sorted(o.latency_ms for o in outcomes)
    exact = sum(1 for o in outcomes if o.expected == o.predicted)

    return GoldReport(
        path=path,
        outcomes=outcomes,
        false_supported_rate=(len(false_supported) / n) if n else 0.0,
        false_supported_count=len(false_supported),
        missing_recall=(len(pred_missing_ok) / len(gold_missing)) if gold_missing else 1.0,
        citation_precision=(len(cited_ok) / len(supported_preds)) if supported_preds else 1.0,
        latency_p50_ms=float(median(latencies)) if latencies else 0.0,
        latency_p95_ms=_percentile(latencies, 0.95),
        exact_match_rate=(exact / n) if n else 0.0,
        n=n,
    )


def gate_ok(
    report: GoldReport,
    *,
    max_false_supported_rate: float = 0.0,
    min_missing_recall: float = 0.85,
    min_citation_precision: float = 0.95,
    max_latency_p95_ms: float = 500.0,
    min_cases: int = 20,
) -> tuple[bool, list[str]]:
    """Release gate for the rules path (strict false-SUPPORTED)."""
    failures: list[str] = []
    if report.n < min_cases:
        failures.append(f"too_few_cases n={report.n} min={min_cases}")
    if report.false_supported_rate > max_false_supported_rate:
        failures.append(
            f"false_supported_rate={report.false_supported_rate:.4f} "
            f"> {max_false_supported_rate}"
        )
    if report.missing_recall < min_missing_recall:
        failures.append(
            f"missing_recall={report.missing_recall:.4f} < {min_missing_recall}"
        )
    if report.citation_precision < min_citation_precision:
        failures.append(
            f"citation_precision={report.citation_precision:.4f} < {min_citation_precision}"
        )
    if report.latency_p95_ms > max_latency_p95_ms:
        failures.append(
            f"latency_p95_ms={report.latency_p95_ms:.1f} > {max_latency_p95_ms}"
        )
    return not failures, failures
