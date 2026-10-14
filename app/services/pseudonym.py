"""Keyed pseudonyms for staff identities shown to patients.

Patients see "Care team member · ref ab12cd34ef" in their access log. The reference is an
HMAC of the staff subject under a server secret, so it is stable (the grievance officer can
match it in the admin audit log) but cannot be reversed by hashing guessed email addresses.
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import Settings, get_settings

_LOCAL_FALLBACK = "local-only-staff-pseudonym-key-not-for-real-data"


def _pseudonym_key(settings: Settings) -> bytes:
    for candidate in (settings.staff_pseudonym_secret, settings.stream_ticket_secret):
        value = (candidate or "").strip()
        if len(value) >= 32:
            return value.encode("utf-8")
    # Local/demo/test without secrets: still keyed, but only safe for synthetic data.
    # The real-data trial gate requires STAFF_PSEUDONYM_SECRET.
    return _LOCAL_FALLBACK.encode("utf-8")


def staff_reference(subject: str, settings: Settings | None = None) -> str:
    """Stable, non-reversible 10-hex reference for a staff subject."""
    cfg = settings or get_settings()
    message = subject.strip().lower().encode("utf-8")
    return hmac.new(_pseudonym_key(cfg), message, hashlib.sha256).hexdigest()[:10]
