"""Time-limited emergency chart access tickets (admin cross-org)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from uuid import uuid4

from app.core.exceptions import AppError

_DEFAULT_TTL_SECONDS = 3600
_LOCK = threading.Lock()
_TICKETS: dict[str, BreakGlassTicket] = {}


@dataclass(frozen=True)
class BreakGlassTicket:
    ticket_id: str
    patient_id: str
    actor: str
    reason: str
    expires_at: float


def issue_ticket(
    *,
    patient_id: str,
    actor: str,
    reason: str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> BreakGlassTicket:
    code = patient_id.strip().upper()
    ttl = max(60, min(int(ttl_seconds), 24 * 3600))
    ticket = BreakGlassTicket(
        ticket_id=str(uuid4()),
        patient_id=code,
        actor=actor.strip()[:64],
        reason=reason.strip()[:500],
        expires_at=time.time() + ttl,
    )
    with _LOCK:
        _purge_locked()
        _TICKETS[ticket.ticket_id] = ticket
    return ticket


def require_valid_ticket(
    ticket_id: str | None,
    *,
    patient_id: str,
    actor: str,
) -> BreakGlassTicket:
    if not ticket_id or not str(ticket_id).strip():
        raise AppError(
            "BREAK_GLASS_REQUIRED",
            "Cross-organization chart access requires an active break-glass ticket "
            "(POST /security/break-glass, then send X-Break-Glass-Id).",
            403,
        )
    tid = str(ticket_id).strip()
    code = patient_id.strip().upper()
    with _LOCK:
        _purge_locked()
        ticket = _TICKETS.get(tid)
    if ticket is None:
        raise AppError(
            "BREAK_GLASS_INVALID",
            "Break-glass ticket was not found or has expired.",
            403,
        )
    if ticket.patient_id != code:
        raise AppError(
            "BREAK_GLASS_MISMATCH",
            "Break-glass ticket does not cover this patient.",
            403,
        )
    if ticket.actor != actor.strip()[:64]:
        raise AppError(
            "BREAK_GLASS_MISMATCH",
            "Break-glass ticket was issued to a different actor.",
            403,
        )
    if ticket.expires_at <= time.time():
        with _LOCK:
            _TICKETS.pop(tid, None)
        raise AppError(
            "BREAK_GLASS_EXPIRED",
            "Break-glass ticket has expired. Request a new ticket.",
            403,
        )
    return ticket


def clear_tickets() -> None:
    """Test helper."""
    with _LOCK:
        _TICKETS.clear()


def _purge_locked() -> None:
    now = time.time()
    expired = [key for key, ticket in _TICKETS.items() if ticket.expires_at <= now]
    for key in expired:
        _TICKETS.pop(key, None)
