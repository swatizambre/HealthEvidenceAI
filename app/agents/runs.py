"""Durable run store for LangGraph review HITL pause/resume.

Keeps an in-process cache for speed and persists to the DB so resume survives
API restarts (correct path for multi-request clinician review).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

_LOCK = Lock()
_RUNS: dict[str, dict[str, Any]] = {}


def save_run(run_id: str, state: dict[str, Any], session: Session | None = None) -> None:
    payload = _json_safe(state)
    with _LOCK:
        _RUNS[run_id] = dict(payload)
    if session is None:
        return
    from app.models import ReviewRun

    row = session.get(ReviewRun, run_id)
    now = datetime.now(UTC)
    if row is None:
        session.add(ReviewRun(run_id=run_id, state_json=payload, updated_at=now))
    else:
        row.state_json = payload
        row.updated_at = now
    session.flush()


def load_run(run_id: str, session: Session | None = None) -> dict[str, Any] | None:
    with _LOCK:
        cached = _RUNS.get(run_id)
        if cached is not None:
            return dict(cached)
    if session is None:
        return None
    from app.models import ReviewRun

    row = session.get(ReviewRun, run_id)
    if row is None:
        return None
    state = dict(row.state_json or {})
    with _LOCK:
        _RUNS[run_id] = dict(state)
    return state


def clear_runs(session: Session | None = None) -> None:
    with _LOCK:
        _RUNS.clear()
    if session is None:
        return
    from sqlalchemy import delete

    from app.models import ReviewRun

    session.execute(delete(ReviewRun))
    session.flush()


def _json_safe(value: Any) -> Any:
    """Ensure run state can round-trip through JSON/DB."""
    return json.loads(json.dumps(value, default=str))
