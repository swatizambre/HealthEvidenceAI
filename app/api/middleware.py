"""Request logging as pure ASGI middleware.

Clinical document text is not written to the log. The route template is used
when Starlette has attached it; otherwise the log records an unmatched request.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

from app.core.logging import request_id_ctx

logger = logging.getLogger("healthevidence.access")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class AccessLogMiddleware:
    """Record request id, route, status, and latency for every HTTP request."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = _header(scope, b"x-request-id")
        request_id = header if header and _REQUEST_ID.fullmatch(header) else str(uuid4())
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            from app.services.observability import bump_counter

            bump_counter("http_requests_total")
        except Exception:  # noqa: BLE001 — never break requests for metrics
            pass

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            route = scope.get("route")
            endpoint = getattr(route, "path", None) or "unmatched"
            logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "latency_ms": max(latency_ms, 0),
                },
            )
            request_id_ctx.reset(token)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None
