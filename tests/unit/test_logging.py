"""Request logs keep routing metadata and leave clinical text out."""

import json
import logging

import pytest
from app.core.logging import JsonFormatter
from fastapi.testclient import TestClient


def test_json_formatter_includes_request_fields() -> None:
    record = logging.LogRecord(
        name="healthevidence.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="http_request",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-123"
    record.endpoint = "/health"
    record.status_code = 200
    record.latency_ms = 4
    payload = json.loads(JsonFormatter().format(record))
    assert payload["timestamp"]
    assert payload["request_id"] == "req-123"
    assert payload["endpoint"] == "/health"
    assert payload["status_code"] == 200
    assert payload["latency_ms"] == 4


def test_patient_request_does_not_log_the_note(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    response = client.get("/api/v1/patients/PAT-000001", headers={"X-Request-ID": "req-patient"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-patient"
    assert "SYNTHEA_RECORD_PAT_000001" not in caplog.text
    assert "BEGIN_UNTRUSTED_RETRIEVED_DATA" not in caplog.text
    records = [record for record in caplog.records if record.message == "http_request"]
    assert records
    assert records[-1].status_code == 200
    assert records[-1].request_id == "req-patient"
    assert records[-1].latency_ms >= 0
    assert "PAT-000001" not in records[-1].endpoint
