"""ABDM / ABHA sandbox stubs — no live network calls."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.services.records import require_patient


def abdm_status(settings: Settings | None = None) -> dict[str, Any]:
    del settings  # reserved for future ABDM_SANDBOX_CLIENT_ID
    get_settings()  # ensure settings load side-effects in app context
    return {
        "status": "not_configured",
        "sandbox": True,
        "phr_registered": False,
        "message": "ABDM sandbox is not configured. See docs/ABDM_SANDBOX.md.",
        "docs": "docs/ABDM_SANDBOX.md",
    }


def link_abha(
    session: Session,
    patient_id: str,
    *,
    abha_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Always 503 until sandbox credentials exist — stores nothing live."""
    del session, patient_id, abha_id
    status = abdm_status(settings)
    raise AppError(
        "ABDM_NOT_CONFIGURED",
        status["message"],
        503,
    )
