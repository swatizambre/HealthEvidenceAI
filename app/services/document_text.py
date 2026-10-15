"""Pull plain text from uploaded clinical files (PDF / text / image bytes).

Images return empty text here — vision providers read the bytes separately.
Not for clinical use; extraction is decision-support assist only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.exceptions import AppError

_MAX_BYTES = 8 * 1024 * 1024
_PDF_TYPES = frozenset({"application/pdf", "application/x-pdf"})
_TEXT_TYPES = frozenset({"text/plain", "text/csv", "application/json"})
_IMAGE_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"})


@dataclass(frozen=True)
class ExtractedText:
    text: str
    media_kind: str  # pdf | text | image
    page_count: int
    char_count: int


def sniff_media_kind(filename: str, content_type: str, data: bytes) -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _PDF_TYPES or name.endswith(".pdf") or data[:4] == b"%PDF":
        return "pdf"
    if ctype in _IMAGE_TYPES or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    if ctype in _TEXT_TYPES or name.endswith((".txt", ".csv", ".md", ".json")):
        return "text"
    if data[:4] == b"%PDF":
        return "pdf"
    # Heuristic: mostly printable → treat as text.
    sample = data[:2000]
    if sample and sum(32 <= b < 127 or b in (9, 10, 13) for b in sample) / max(len(sample), 1) > 0.85:
        return "text"
    raise AppError(
        "DOCUMENT_TYPE_UNSUPPORTED",
        "Upload a PDF, plain-text export, or JPEG/PNG/WebP image of a lab report or prescription.",
        400,
    )


def extract_plain_text(
    *,
    data: bytes,
    filename: str = "",
    content_type: str = "",
) -> ExtractedText:
    if not data:
        raise AppError("DOCUMENT_EMPTY", "Uploaded file is empty.", 400)
    if len(data) > _MAX_BYTES:
        raise AppError(
            "DOCUMENT_TOO_LARGE",
            f"File exceeds {_MAX_BYTES // (1024 * 1024)} MB limit.",
            400,
        )
    kind = sniff_media_kind(filename, content_type, data)
    if kind == "image":
        return ExtractedText(text="", media_kind="image", page_count=1, char_count=0)
    if kind == "text":
        text = _decode_text(data)
        return ExtractedText(
            text=text,
            media_kind="text",
            page_count=1,
            char_count=len(text),
        )
    text, pages = _pdf_text(data)
    return ExtractedText(
        text=text,
        media_kind="pdf",
        page_count=pages,
        char_count=len(text),
    )


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def _pdf_text(data: bytes) -> tuple[str, int]:
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError as exc:
        raise AppError(
            "PDF_SUPPORT_MISSING",
            "PDF text extraction requires the pypdf package.",
            500,
        ) from exc
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise AppError(
            "PDF_UNREADABLE",
            f"Could not open PDF: {exc}",
            400,
        ) from exc
    pages: list[str] = []
    for page in reader.pages[:40]:
        try:
            chunk = page.extract_text() or ""
        except Exception:
            chunk = ""
        if chunk.strip():
            pages.append(chunk.strip())
    text = "\n\n".join(pages).strip()
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, len(reader.pages)
