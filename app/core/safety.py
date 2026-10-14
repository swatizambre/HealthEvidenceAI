"""Safety boundary for evidence-organization outputs."""

from __future__ import annotations

import re
from typing import Any

PROTOTYPE_BANNER = "Not for clinical use or diagnosis."
DISCLAIMER = (
    "This output is decision support for prior-auth paperwork (rule check and/or optional AI). "
    "It is not a diagnosis or clinical decision. Human review is required."
)

AUTONOMOUS_DECISION_VALUES = frozenset(
    {
        "APPROVE",
        "APPROVED",
        "DENY",
        "DENIED",
        "DIAGNOSE",
        "DIAGNOSIS",
        "PRESCRIBE",
        "PRESCRIPTION",
    }
)


def contains_autonomous_decision(payload: Any) -> bool:
    """Return True when a field is itself an autonomous decision token."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).upper() in AUTONOMOUS_DECISION_VALUES:
                return True
            if contains_autonomous_decision(value):
                return True
        return False
    if isinstance(payload, list):
        return any(contains_autonomous_decision(item) for item in payload)
    if isinstance(payload, str):
        return payload.strip().upper() in AUTONOMOUS_DECISION_VALUES
    return False


_UNSAFE_PHRASE = re.compile(
    r"\b("
    r"approv(?:e|ed|al|ing)|"
    r"den(?:y|ies|ied|ial)|"
    r"diagnos(?:e|ed|is|ing)|"
    r"prescrib(?:e|ed|ing)|"
    r"prescription"
    r")\b",
    re.IGNORECASE,
)


# Desk vocabulary that names a document field or an insurer's recorded outcome, not a
# decision made by this system (e.g. "Provisional diagnosis with ICD-10", "approved
# amount"). Neutralised before the phrase check so checklist labels can appear in
# summaries; first-person or system decisions ("we approve…") are still caught.
_FIELD_PHRASES = re.compile(
    r"\b(?:provisional|final|discharge|admission|primary|secondary|working|pre-?auth|"
    r"principal|differential)\s+diagnos(?:is|es)\b"
    r"|\bdiagnos(?:is|es)\s+(?:code|codes|with\s+icd(?:-?10)?|and\s+icd(?:-?10)?)\b"
    r"|\b(?:approved|approval)\s+(?:amount|procedure|limit|letter|date|status)\b"
    r"|\b(?:insurer|tpa|pre-?auth|cashless)\s+approval\b"
    r"|\brecord(?:ed)?\s+approval\b",
    re.IGNORECASE,
)


def contains_unsafe_decision_language(text: str) -> bool:
    """Broader phrase check for free-text model output (help chat, summaries)."""
    value = _FIELD_PHRASES.sub("field", (text or "")).strip()
    if not value:
        return False
    if contains_autonomous_decision(value):
        return True
    # Allow safe product sentences that explicitly refuse these actions.
    lower = value.lower()
    if "does not approve" in lower or "not an approval" in lower or "never approve" in lower:
        if not re.search(r"\b(diagnos|prescrib)", lower):
            # Still flag if it affirms a denial/approval elsewhere.
            if re.search(r"\b(we|i|system)\s+(approve|deny|diagnos|prescrib)", lower):
                return True
            if "does not deny" in lower or "not a denial" in lower or "never deny" in lower:
                return False
    return _UNSAFE_PHRASE.search(value) is not None and not (
        "does not" in lower
        or "do not" in lower
        or "never" in lower
        or "not a" in lower
        or "not an" in lower
    )


def enforce_decision_support(payload: Any) -> None:
    from app.core.exceptions import AppError

    if contains_autonomous_decision(payload):
        raise AppError(
            "UNSAFE_OUTPUT_BLOCKED",
            "The review was blocked because the output resembled an autonomous clinical decision.",
            500,
        )
    if isinstance(payload, dict):
        for key in ("report_summary", "reason", "reply", "packet_summary"):
            text = payload.get(key)
            if isinstance(text, str) and contains_unsafe_decision_language(text):
                # Allow explicit refusal language in disclaimers.
                lower = text.lower()
                if any(
                    marker in lower
                    for marker in (
                        "does not approve",
                        "not an approval",
                        "never approve",
                        "not a denial",
                        "does not deny",
                        "not a diagnosis",
                    )
                ):
                    continue
                raise AppError(
                    "UNSAFE_OUTPUT_BLOCKED",
                    "The review was blocked because free-text output resembled a clinical decision.",
                    500,
                )
