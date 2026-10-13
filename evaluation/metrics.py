"""Clinical-safety metrics for criterion-level gold evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

STATUS_SUPPORTED = "SUPPORTED"
STATUS_MISSING = "MISSING"
STATUS_NOT_SUPPORTED = "NOT_SUPPORTED"
STATUS_UNKNOWN = "UNKNOWN"
STATUSES = (STATUS_SUPPORTED, STATUS_NOT_SUPPORTED, STATUS_MISSING, STATUS_UNKNOWN)


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
    # Predicted SUPPORTED / cases whose gold is NOT SUPPORTED (the cases that could go wrong).
    false_supported_rate: float
    false_supported_count: int
    missing_recall: float
    # Gold SUPPORTED cases also predicted SUPPORTED.
    supported_recall: float
    # Predicted SUPPORTED rows that carry >=1 citation. Presence only: it does not check
    # that the cited text entails the claim (that is the verifier's job).
    citation_presence: float
    latency_p50_ms: float
    latency_p95_ms: float
    exact_match_rate: float
    n: int
    # confusion[expected][predicted] = count
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def citation_precision(self) -> float:
        """Deprecated alias for :attr:`citation_presence`."""
        return self.citation_presence

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "n": self.n,
            "gold_counts": {s: sum(self.confusion.get(s, {}).values()) for s in STATUSES},
            "false_supported_rate": round(self.false_supported_rate, 4),
            "false_supported_count": self.false_supported_count,
            "missing_recall": round(self.missing_recall, 4),
            "supported_recall": round(self.supported_recall, 4),
            "citation_presence": round(self.citation_presence, 4),
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "exact_match_rate": round(self.exact_match_rate, 4),
            "confusion_expected_by_predicted": self.confusion,
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


def confusion_counts(outcomes: list[CaseOutcome]) -> dict[str, dict[str, int]]:
    seen = {o.expected for o in outcomes} | {o.predicted for o in outcomes}
    statuses = list(STATUSES) + sorted(seen - set(STATUSES))
    table = {exp: dict.fromkeys(statuses, 0) for exp in statuses}
    for o in outcomes:
        table[o.expected][o.predicted] += 1
    return table


def summarize_outcomes(path: str, outcomes: list[CaseOutcome]) -> GoldReport:
    n = len(outcomes)
    gold_not_supported = [o for o in outcomes if o.expected != STATUS_SUPPORTED]
    false_supported = [o for o in gold_not_supported if o.predicted == STATUS_SUPPORTED]
    gold_supported = [o for o in outcomes if o.expected == STATUS_SUPPORTED]
    supported_hit = [o for o in gold_supported if o.predicted == STATUS_SUPPORTED]
    gold_missing = [o for o in outcomes if o.expected == STATUS_MISSING]
    pred_missing_ok = [o for o in gold_missing if o.predicted == STATUS_MISSING]
    supported_preds = [o for o in outcomes if o.predicted == STATUS_SUPPORTED]
    cited_ok = [o for o in supported_preds if o.citation_count > 0]
    latencies = sorted(o.latency_ms for o in outcomes)
    exact = sum(1 for o in outcomes if o.expected == o.predicted)

    return GoldReport(
        path=path,
        outcomes=outcomes,
        false_supported_rate=(
            len(false_supported) / len(gold_not_supported) if gold_not_supported else 0.0
        ),
        false_supported_count=len(false_supported),
        missing_recall=(len(pred_missing_ok) / len(gold_missing)) if gold_missing else 1.0,
        supported_recall=(len(supported_hit) / len(gold_supported)) if gold_supported else 1.0,
        citation_presence=(len(cited_ok) / len(supported_preds)) if supported_preds else 1.0,
        latency_p50_ms=float(median(latencies)) if latencies else 0.0,
        latency_p95_ms=_percentile(latencies, 0.95),
        exact_match_rate=(exact / n) if n else 0.0,
        n=n,
        confusion=confusion_counts(outcomes),
    )


def gate_ok(
    report: GoldReport,
    *,
    max_false_supported_rate: float = 0.0,
    min_missing_recall: float = 0.85,
    min_supported_recall: float = 0.9,
    min_citation_presence: float = 0.95,
    max_latency_p95_ms: float = 500.0,
    min_cases: int = 20,
    min_citation_precision: float | None = None,
) -> tuple[bool, list[str]]:
    """Release gate for the rules path (strict false-SUPPORTED).

    ``min_citation_precision`` is a deprecated alias for ``min_citation_presence``.
    """
    if min_citation_precision is not None:
        min_citation_presence = min_citation_precision
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
    if report.supported_recall < min_supported_recall:
        failures.append(
            f"supported_recall={report.supported_recall:.4f} < {min_supported_recall}"
        )
    if report.citation_presence < min_citation_presence:
        failures.append(
            f"citation_presence={report.citation_presence:.4f} < {min_citation_presence}"
        )
    if report.latency_p95_ms > max_latency_p95_ms:
        failures.append(
            f"latency_p95_ms={report.latency_p95_ms:.1f} > {max_latency_p95_ms}"
        )
    return not failures, failures
