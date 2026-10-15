"""Versioned legal / privacy notice texts shipped under docs/legal/."""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import NotFoundError

_ROOT = Path(__file__).resolve().parents[2] / "docs" / "legal"

_NOTICE_FILES: dict[str, dict[str, str]] = {
    "privacy-notice": {
        "en": "privacy-notice.v1.en.md",
        "hi": "privacy-notice.v1.hi.md",
        "mr": "privacy-notice.v1.mr.md",
    },
    "ai-intended-use": {
        "en": "ai-intended-use.v1.en.md",
    },
    "genetic-data-policy": {
        "en": "genetic-data-policy.v1.en.md",
    },
}

_VERSIONS = {
    "privacy-notice": "privacy-notice.v1",
    "ai-intended-use": "ai-intended-use.v1",
    "genetic-data-policy": "genetic-data-policy.v1",
}


def list_notice_ids() -> list[dict[str, str]]:
    return [
        {"id": notice_id, "notice_version": version, "langs": ",".join(sorted(_NOTICE_FILES[notice_id]))}
        for notice_id, version in _VERSIONS.items()
    ]


def get_notice(notice_id: str, lang: str = "en") -> dict[str, str]:
    key = (notice_id or "").strip().lower()
    files = _NOTICE_FILES.get(key)
    if not files:
        raise NotFoundError("NOTICE_NOT_FOUND", f"Unknown notice id: {notice_id}")
    code = (lang or "en").strip().lower()[:8] or "en"
    filename = files.get(code) or files.get("en")
    if not filename:
        raise NotFoundError("NOTICE_LANG_MISSING", f"No language available for notice {notice_id}")
    path = _ROOT / filename
    if not path.is_file():
        raise NotFoundError("NOTICE_FILE_MISSING", f"Notice file missing: {filename}")
    return {
        "id": key,
        "notice_version": _VERSIONS[key],
        "language": code if code in files else "en",
        "format": "markdown",
        "body": path.read_text(encoding="utf-8"),
    }
