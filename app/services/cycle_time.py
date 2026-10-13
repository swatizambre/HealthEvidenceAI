"""Packet cycle-time metrics for PA desk ops (documentation readiness only)."""

from __future__ import annotations

from datetime import UTC, datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuthorizationCase


def stamp_prep_started(case: AuthorizationCase, *, when: datetime | None = None) -> None:
    """Mark first prepare / gap work start (idempotent)."""
    if getattr(case, "prep_started_at", None) is None:
        case.prep_started_at = when or datetime.now(UTC)


def stamp_review_ready(case: AuthorizationCase, *, when: datetime | None = None) -> None:
    """Mark when case first becomes ready for clinician HITL (idempotent)."""
    if getattr(case, "review_ready_at", None) is None:
        case.review_ready_at = when or datetime.now(UTC)


def elapsed_minutes(
    start: datetime | None,
    end: datetime | None,
    *,
    now: datetime | None = None,
) -> int | None:
    if start is None:
        return None
    finish = end or now or datetime.now(UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if finish.tzinfo is None:
        finish = finish.replace(tzinfo=UTC)
    seconds = (finish - start).total_seconds()
    if seconds < 0:
        return 0
    return int(round(seconds / 60.0))


def case_cycle_minutes(case: AuthorizationCase, *, now: datetime | None = None) -> int | None:
    start = getattr(case, "prep_started_at", None) or getattr(case, "created_at", None)
    end = getattr(case, "review_ready_at", None)
    if end is None and str(getattr(case, "status", "") or "") not in {
        "ready_for_human",
        "closed_as_draft",
    }:
        # Still open — aging from prep start.
        return elapsed_minutes(start, None, now=now)
    return elapsed_minutes(start, end, now=now)


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def packet_ops_metrics(session: Session, *, org_id: str | None = None) -> dict[str, object]:
    """Aggregate prep→ready cycle times for closed-enough cases + open aging."""
    if org_id:
        from app.models import Patient

        cases = list(
            session.scalars(
                select(AuthorizationCase)
                .join(Patient, AuthorizationCase.patient_id == Patient.id)
                .where(Patient.org_id == org_id)
            ).all()
        )
    else:
        cases = list(session.scalars(select(AuthorizationCase)).all())
    # Cap "typical" samples so stale seed cases (months open) do not dominate the desk.
    max_typical_minutes = 8 * 60.0
    completed: list[float] = []
    open_aging: list[float] = []
    now = datetime.now(UTC)
    for case in cases:
        start = getattr(case, "prep_started_at", None) or getattr(case, "created_at", None)
        ready = getattr(case, "review_ready_at", None)
        status = str(getattr(case, "status", "") or "queued")
        if ready is not None:
            mins = elapsed_minutes(start, ready)
            if mins is not None and 0 <= mins <= max_typical_minutes:
                completed.append(float(mins))
        elif status in {"ready_for_human", "needs_documentation", "queued"}:
            # Open work ages separately — never inflate "typical time".
            mins = elapsed_minutes(start, None, now=now)
            if mins is not None:
                open_aging.append(float(mins))

    from app.core.config import get_settings

    sla = max(15, int(get_settings().packet_sla_minutes or 240))
    completed_sorted = sorted(completed)
    open_sorted = sorted(open_aging)
    sla_breaches = sum(1 for mins in open_sorted if mins >= sla)
    return {
        "sample_size": len(completed_sorted),
        "median_minutes": (
            float(median(completed_sorted)) if completed_sorted else None
        ),
        "p75_minutes": _percentile(completed_sorted, 0.75),
        "mean_minutes": (
            round(sum(completed_sorted) / len(completed_sorted), 1)
            if completed_sorted
            else None
        ),
        "open_aging_sample_size": len(open_sorted),
        "open_aging_median_minutes": (
            float(median(open_sorted)) if open_sorted else None
        ),
        "sla_minutes": sla,
        "sla_breach_count": sla_breaches,
        "unit": "minutes",
        "definition": (
            "prep_started_at → review_ready_at for finished cycles ≤8h "
            "(documentation readiness only; open cases excluded from typical); "
            f"SLA breach = open aging ≥ {sla}m"
        ),
    }
