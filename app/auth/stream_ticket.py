"""Short-lived, single-purpose tickets for the SSE desk stream.

Browsers cannot attach an Authorization header to ``EventSource``, so the desk first
calls ``POST /api/v1/events/stream-ticket`` with its normal bearer token and then opens
``/api/v1/events/stream?ticket=...``. The ticket is an HS256 JWT signed with
``STREAM_TICKET_SECRET``; it carries only the principal fields the stream needs, has its
own audience and ``purpose="sse"`` claim (so it is useless as an API bearer token), and
expires after ``STREAM_TICKET_TTL_SECONDS`` (60 s by default). Each ticket id is accepted
once per replica to blunt replay from logs or browser history.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any
from uuid import uuid4

import jwt

from app.auth.oidc import AuthPrincipal
from app.core.config import Settings
from app.core.exceptions import AppError

STREAM_TICKET_AUDIENCE = "healthevidence-sse"
STREAM_TICKET_PURPOSE = "sse"

_USED_LOCK = Lock()
_USED_TICKETS: dict[str, float] = {}


def issue_stream_ticket(principal: AuthPrincipal | None, settings: Settings) -> tuple[str, int]:
    """Sign a ticket for ``principal``; returns (ticket, expires_in_seconds)."""
    ttl = max(5, min(int(settings.stream_ticket_ttl_seconds or 60), 300))
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": principal.subject if principal is not None else "anonymous",
        "email": principal.email if principal is not None else "",
        "roles": list(principal.roles) if principal is not None else [],
        "aud": STREAM_TICKET_AUDIENCE,
        "purpose": STREAM_TICKET_PURPOSE,
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + ttl,
    }
    if principal is not None:
        if principal.org_id:
            claims["org_id"] = principal.org_id
        if principal.org_code:
            claims["org_code"] = principal.org_code
        if principal.patient_id:
            claims["patient_id"] = principal.patient_id
    token = jwt.encode(claims, settings.resolve_stream_ticket_secret(), algorithm="HS256")
    return token, ttl


def verify_stream_ticket(ticket: str, settings: Settings) -> AuthPrincipal:
    """Validate signature, audience, purpose, expiry, and one-time use."""
    try:
        claims = jwt.decode(
            ticket,
            settings.resolve_stream_ticket_secret(),
            algorithms=["HS256"],
            audience=STREAM_TICKET_AUDIENCE,
            options={"require": ["exp", "sub", "jti"]},
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError("STREAM_TICKET_INVALID", "Stream ticket is invalid or expired.", 401) from exc
    if claims.get("purpose") != STREAM_TICKET_PURPOSE:
        raise AppError("STREAM_TICKET_INVALID", "Stream ticket is invalid or expired.", 401)
    _consume(str(claims["jti"]), float(claims["exp"]))
    roles = claims.get("roles")
    return AuthPrincipal(
        subject=str(claims["sub"]),
        email=str(claims.get("email") or ""),
        roles=tuple(str(item) for item in roles) if isinstance(roles, list) else (),
        raw_claims={"auth": "stream_ticket", **claims},
        patient_id=_opt_str(claims.get("patient_id")),
        org_id=_opt_str(claims.get("org_id")),
        org_code=_opt_str(claims.get("org_code")),
    )


def _consume(jti: str, expires_at: float) -> None:
    now = time.time()
    with _USED_LOCK:
        for key in [key for key, exp in _USED_TICKETS.items() if exp < now]:
            del _USED_TICKETS[key]
        if jti in _USED_TICKETS:
            raise AppError("STREAM_TICKET_INVALID", "Stream ticket was already used.", 401)
        _USED_TICKETS[jti] = expires_at


def _opt_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
