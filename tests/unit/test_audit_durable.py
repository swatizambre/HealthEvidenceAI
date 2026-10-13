"""record_audit_durable must never fail silently (logged + counted, no PHI)."""

from __future__ import annotations

import logging

import pytest
from app.services.audit import AUDIT_DURABLE_FAILURE_COUNTER, record_audit_durable
from app.services.observability import prometheus_text, snapshot_counters
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_durable_audit_failure_logs_warning_and_counts(caplog: pytest.LogCaptureFixture) -> None:
    # Empty in-memory DB: no audit_events table, so the insert fails.
    engine = create_engine("sqlite://")
    session = Session(bind=engine)
    before = snapshot_counters().get(AUDIT_DURABLE_FAILURE_COUNTER, 0.0)
    try:
        with caplog.at_level(logging.WARNING, logger="healthevidence.audit"):
            result = record_audit_durable(
                session,
                action="org_scope_denied",
                actor="user-123",
                resource_type="patient",
                resource_id="PAT-000042",
                status="denied",
                detail="Secret clinical note body",
            )
    finally:
        session.close()
        engine.dispose()

    assert result is None
    after = snapshot_counters().get(AUDIT_DURABLE_FAILURE_COUNTER, 0.0)
    assert after == before + 1
    records = [r for r in caplog.records if r.name == "healthevidence.audit"]
    assert records, "expected a warning on the healthevidence.audit logger"
    message = records[-1].getMessage()
    assert records[-1].levelno == logging.WARNING
    assert "org_scope_denied" in message
    assert "resource_type=patient" in message
    assert "status=denied" in message
    assert "OperationalError" in message
    # Identifiers / free text never reach the log line.
    assert "PAT-000042" not in message
    assert "user-123" not in message
    assert "Secret clinical note body" not in message
    assert "healthevidence_audit_durable_write_failures_total" in prometheus_text()


def test_durable_audit_none_session_is_noop() -> None:
    assert (
        record_audit_durable(
            None,
            action="x",
            actor="y",
            resource_type="z",
            resource_id="r",
            status="ok",
        )
        is None
    )
