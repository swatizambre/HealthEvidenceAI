"""Agent-run observability: in-process buffer + optional OTLP/JSON export."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import Lock

import httpx

logger = logging.getLogger("healthevidence.observability")


@dataclass
class SpanRecord:
    trace_id: str
    run_id: str
    agent: str
    node: str
    model: str = ""
    tool: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    status: str = "ok"
    error: str = ""


@dataclass
class TraceBuffer:
    spans: list[SpanRecord] = field(default_factory=list)


_LOCK = Lock()
_TRACES: dict[str, TraceBuffer] = {}
_COUNTERS: dict[str, float] = {
    "http_requests_total": 0.0,
    "review_runs_total": 0.0,
    "review_runs_error_total": 0.0,
    "agent_span_total": 0.0,
    "agent_span_latency_ms_sum": 0.0,
    "audit_durable_write_failures_total": 0.0,
}


def new_trace_id() -> str:
    return str(uuid.uuid4())


def new_run_id() -> str:
    return str(uuid.uuid4())


def bump_counter(name: str, amount: float = 1.0) -> None:
    with _LOCK:
        _COUNTERS[name] = float(_COUNTERS.get(name, 0.0)) + amount


def snapshot_counters() -> dict[str, float]:
    with _LOCK:
        return dict(_COUNTERS)


def record_span(span: SpanRecord) -> None:
    with _LOCK:
        buffer = _TRACES.setdefault(span.run_id, TraceBuffer())
        buffer.spans.append(span)
        _COUNTERS["agent_span_total"] = float(_COUNTERS.get("agent_span_total", 0.0)) + 1.0
        _COUNTERS["agent_span_latency_ms_sum"] = (
            float(_COUNTERS.get("agent_span_latency_ms_sum", 0.0)) + float(span.latency_ms)
        )
        if span.status == "error":
            _COUNTERS["review_runs_error_total"] = (
                float(_COUNTERS.get("review_runs_error_total", 0.0)) + 1.0
            )
    _export_span(span)


def get_trace(run_id: str) -> list[dict[str, object]]:
    with _LOCK:
        buffer = _TRACES.get(run_id)
        if buffer is None:
            return []
        return [asdict(span) for span in buffer.spans]


def _export_span(span: SpanRecord) -> None:
    """Best-effort durable export when OTEL/Langfuse endpoints are configured."""
    try:
        from app.core.config import get_settings

        if get_settings().external_llm_phi_blocked():
            # Chart-linked spans must not leave the boundary without BAA / egress attestation.
            if os.environ.get("HE_TRACE_LOG", "").lower() in {"1", "true", "yes"}:
                logger.info("agent_span_local_only %s", json.dumps(asdict(span), default=str))
            return
    except Exception:  # noqa: BLE001 — fail closed: never export when the PHI gate is unknown
        if os.environ.get("HE_TRACE_LOG", "").lower() in {"1", "true", "yes"}:
            logger.info("agent_span_local_only %s", json.dumps(asdict(span), default=str))
        return
    endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    langfuse_host = (os.environ.get("LANGFUSE_HOST") or "").strip()
    payload = asdict(span)
    if endpoint:
        url = endpoint.rstrip("/") + "/v1/traces"
        try:
            httpx.post(url, json={"spans": [payload]}, timeout=2.0)
        except Exception as exc:  # noqa: BLE001 — never fail the desk for telemetry
            logger.debug("otel_export_failed err=%s", exc)
        return
    if langfuse_host and os.environ.get("ENABLE_TRACING", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # Lightweight JSON sink — full Langfuse SDK is optional later.
        try:
            httpx.post(
                langfuse_host.rstrip("/") + "/api/public/ingestion",
                json={"batch": [{"type": "span", "body": payload}]},
                timeout=2.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("langfuse_export_failed err=%s", exc)
            return
    if os.environ.get("HE_TRACE_LOG", "").lower() in {"1", "true", "yes"}:
        logger.info("agent_span %s", json.dumps(payload, default=str))


class span_timer:
    def __init__(
        self,
        *,
        trace_id: str,
        run_id: str,
        agent: str,
        node: str,
        model: str = "",
        tool: str = "",
    ) -> None:
        self.span = SpanRecord(
            trace_id=trace_id,
            run_id=run_id,
            agent=agent,
            node=node,
            model=model,
            tool=tool,
        )
        self._started = 0.0

    def __enter__(self) -> SpanRecord:
        self._started = time.perf_counter()
        return self.span

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> None:
        self.span.latency_ms = round((time.perf_counter() - self._started) * 1000, 2)
        if exc is not None:
            self.span.status = "error"
            self.span.error = str(exc)[:300]
        record_span(self.span)


def prometheus_text() -> str:
    """Prometheus exposition for desk SLIs (process-local; scrape per replica)."""
    counters = snapshot_counters()
    lines = [
        "# HELP healthevidence_http_requests_total HTTP requests observed by access middleware.",
        "# TYPE healthevidence_http_requests_total counter",
        f"healthevidence_http_requests_total {counters.get('http_requests_total', 0.0)}",
        "# HELP healthevidence_agent_span_total Agent node spans recorded.",
        "# TYPE healthevidence_agent_span_total counter",
        f"healthevidence_agent_span_total {counters.get('agent_span_total', 0.0)}",
        "# HELP healthevidence_agent_span_latency_ms_sum Sum of agent span latency in ms.",
        "# TYPE healthevidence_agent_span_latency_ms_sum counter",
        f"healthevidence_agent_span_latency_ms_sum {counters.get('agent_span_latency_ms_sum', 0.0)}",
        "# HELP healthevidence_review_runs_error_total Agent spans marked error.",
        "# TYPE healthevidence_review_runs_error_total counter",
        f"healthevidence_review_runs_error_total {counters.get('review_runs_error_total', 0.0)}",
        "# HELP healthevidence_audit_durable_write_failures_total Durable audit rows that failed to commit.",
        "# TYPE healthevidence_audit_durable_write_failures_total counter",
        "healthevidence_audit_durable_write_failures_total "
        f"{counters.get('audit_durable_write_failures_total', 0.0)}",
    ]
    return "\n".join(lines) + "\n"
