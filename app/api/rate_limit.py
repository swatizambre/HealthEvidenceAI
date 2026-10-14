"""In-process sliding-window rate limiting (pure ASGI middleware).

Limits are enforced **per API replica**: each process keeps its own counters, so the
effective cluster-wide ceiling is ``limit x replicas``. A shared Redis-backed limiter
(or ingress-level limiting) is future work for horizontally scaled deployments.

Groups (requests per rolling 60 s window):

* ``auth``   — ``/api/v1/auth/*`` (non-GET: token minting / credential flows), keyed by
  client IP. Read-only ``GET /auth/me`` and ``/auth/capabilities`` stay unlimited so a
  whole ward behind one NAT address is not locked out of page loads.
* ``ingest`` — ``/api/v1/opd/*`` and ``/api/v1/hospital/pipeline/*``, keyed by principal
  subject when authenticated, else client IP.
* ``search`` — ``/api/v1/evidence/search`` and ``/api/v1/tools/invoke``, same keying.

Exceeding a limit returns 429 in the app's standard error shape with ``Retry-After``.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.core.config import Settings
from app.core.logging import request_id_ctx

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

WINDOW_SECONDS = 60.0
_MAX_TRACKED_KEYS = 50_000


@dataclass(frozen=True)
class RateLimitRule:
    group: str
    limit: int
    per_principal: bool


class SlidingWindowLimiter:
    """Thread-safe sliding-window log keyed by (group, client)."""

    def __init__(self, window_seconds: float = WINDOW_SECONDS) -> None:
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int, now: float | None = None) -> float:
        """Record a request; return 0.0 if allowed, else seconds until a slot frees up."""
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= _MAX_TRACKED_KEYS:
                    self._evict_idle(cutoff)
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(bucket[0] + self.window_seconds - current, 0.001)
            bucket.append(current)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict_idle(self, cutoff: float) -> None:
        for key in [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]:
            del self._hits[key]


def rule_for_path(path: str, settings: Settings, method: str = "POST") -> RateLimitRule | None:
    if path.startswith("/api/v1/auth/") or path == "/api/v1/auth":
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return None
        # Demo role switching mints a dev token per switch; limiting it only breaks the
        # walkthrough. Dev minting is never enabled in pilot / trial / shared live.
        if path.rstrip("/") == "/api/v1/auth/dev-token" and settings.dev_token_allowed():
            return None
        return RateLimitRule("auth", settings.rate_limit_auth_per_minute, per_principal=False)
    if (
        path.startswith("/api/v1/opd/")
        or path == "/api/v1/opd"
        or path.startswith("/api/v1/hospital/pipeline")
    ):
        return RateLimitRule("ingest", settings.rate_limit_ingest_per_minute, per_principal=True)
    if path in {"/api/v1/evidence/search", "/api/v1/tools/invoke"}:
        return RateLimitRule("search", settings.rate_limit_search_per_minute, per_principal=True)
    return None


class RateLimitMiddleware:
    """Reject over-limit requests with 429 before they reach routing or the database.

    Registered inside AuthMiddleware so per-principal groups can key on the
    authenticated subject (``request.state.principal``) when one is present.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.limiter = SlidingWindowLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_active():
            await self.app(scope, receive, send)
            return
        rule = rule_for_path(
            str(scope.get("path") or ""), self.settings, str(scope.get("method") or "GET")
        )
        if rule is None or rule.limit <= 0:
            await self.app(scope, receive, send)
            return
        key = f"{rule.group}:{self._client_key(scope, rule)}"
        retry_after = self.limiter.hit(key, rule.limit)
        if retry_after <= 0:
            await self.app(scope, receive, send)
            return
        await _send_429(send, retry_after)

    def _client_key(self, scope: Scope, rule: RateLimitRule) -> str:
        if rule.per_principal:
            # AuthMiddleware stores the principal on request.state, i.e. scope["state"].
            state = scope.get("state")
            if isinstance(state, Mapping):
                principal = state.get("principal")
            else:
                principal = getattr(state, "principal", None)
            subject = str(getattr(principal, "subject", "") or "")
            if subject:
                return f"sub:{subject}"
        return f"ip:{self._client_ip(scope)}"

    def _client_ip(self, scope: Scope) -> str:
        if self.settings.rate_limit_trust_proxy_headers:
            forwarded = _header(scope, b"x-forwarded-for")
            if forwarded:
                hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
                if hops:
                    return hops[-1]
        client = scope.get("client")
        if isinstance(client, tuple | list) and client:
            return str(client[0])
        return "unknown"


async def _send_429(send: Send, retry_after: float) -> None:
    seconds = max(1, math.ceil(retry_after))
    body = json.dumps(
        {
            "error_code": "RATE_LIMITED",
            "message": "Too many requests. Please retry shortly.",
            "request_id": request_id_ctx.get(),
        }
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"retry-after", str(seconds).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None
