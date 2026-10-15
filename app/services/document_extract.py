"""AI + heuristic semantic extraction from lab reports and prescriptions.

Turns uploaded PDF/image/text into structured OPD fields (labs, meds, note).
Staff must review before chart ingest. Not for clinical use / not a diagnosis.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Literal

import httpx

from app.agents.providers import build_llm
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, LLMUnavailable
from app.schemas.api import (
    DocumentExtractResponse,
    OpdDiagnosisIn,
    OpdLabIn,
    OpdMedicationIn,
    OpdVitalIn,
)
from app.services.clinical_intelligence import _parse_json
from app.services.document_text import ExtractedText, extract_plain_text

logger = logging.getLogger("healthevidence.document_extract")

DocKind = Literal["auto", "lab_report", "prescription", "clinical_note"]

_EXTRACT_SYSTEM = (
    "You extract structured fields from a clinical document for prior-auth chart prep. "
    "Return JSON only (no markdown). Do not diagnose, prescribe, approve, or deny care. "
    "Only include values visibly present in the source. Use empty arrays when unknown. "
    "Schema: {"
    '"document_kind":"lab_report|prescription|clinical_note|unknown",'
    '"chief_complaint":"",'
    '"history_of_present_illness":"",'
    '"assessment_and_plan":"",'
    '"note":"",'
    '"procedure":"",'
    '"diagnoses":[{"display":"","code":""}],'
    '"labs":[{"test_name":"","value":"","unit":""}],'
    '"medications":[{"name":"","dose":"","frequency":"","route":"","status":"active"}],'
    '"vitals":[{"name":"","value":"","unit":""}],'
    '"warnings":[""]'
    "}"
)

_LAB_LINE = re.compile(
    r"(?im)^[\s\*•\-]*([A-Za-z][A-Za-z0-9 /\-\(\)%]{1,60}?)\s*[:=-]?\s*"
    r"([<>]?\d+(?:\.\d+)?)\s*([%a-zA-Zµμ/^\d\.\-]{0,24})\s*$"
)
_KNOWN_LABS = re.compile(
    r"(?i)\b(hba1c|hemoglobin\s*a1c|a1c|fasting\s*glucose|glucose|fbs|rbs|"
    r"creatinine|egfr|bun|hdl|ldl|triglycerides|cholesterol|tsh|free\s*t4|"
    r"hemoglobin|wbc|platelet|inr|pt|a1c)\b"
    r"[^\n]{0,40}?"
    r"([<>]?\d+(?:\.\d+)?)\s*([%a-zA-Zµμ/^\d\.\-]{0,16})?"
)
_MED_LINE = re.compile(
    # Use [ \t]+ (not \\s+) after the drug name so a header like "Prescription"
    # cannot consume the following medication line via a newline match.
    r"(?im)^[ \t\*•\-]*(?:tab\.?|cap\.?|inj\.?|syrup|syp\.?)?[ \t]+"
    r"([A-Za-z][A-Za-z0-9\-]{1,40})"
    r"(?:[ \t]+(\d+(?:\.\d+)?[ \t]*(?:mg|mcg|g|ml|iu|units?)))?"
    r"(?:[ \t]+(od|bd|bid|tid|qid|hs|sos|once[ \t]+daily|twice[ \t]+daily))?"
    r"[ \t]*$"
)


def extract_clinical_document(
    *,
    data: bytes,
    filename: str = "",
    content_type: str = "",
    document_kind: DocKind = "auto",
    settings: Settings | None = None,
) -> DocumentExtractResponse:
    """Extract structured visit fields from an uploaded clinical file."""
    cfg = settings or get_settings()
    pulled = extract_plain_text(data=data, filename=filename, content_type=content_type)
    source_text = pulled.text
    method = "heuristic"
    warnings: list[str] = []

    if pulled.media_kind == "image":
        vision = _try_vision_extract(
            data=data,
            content_type=content_type or "image/jpeg",
            filename=filename,
            document_kind=document_kind,
            settings=cfg,
        )
        if vision is not None:
            return vision
        raise AppError(
            "IMAGE_VISION_REQUIRED",
            "Image prescriptions/lab photos need a vision-capable LLM "
            "(LLM_PROVIDER=openai or gemini with API key). "
            "Alternatively upload a text PDF or type values on the visit form.",
            400,
        )

    if not source_text.strip():
        raise AppError(
            "DOCUMENT_NO_TEXT",
            "No readable text was found (scanned PDF without OCR). "
            "Upload a text-based PDF, a photo with openai/gemini vision, or type the values.",
            400,
        )

    heuristic = _heuristic_extract(source_text, document_kind=document_kind)
    ai_payload: dict[str, Any] | None = None
    try:
        ai_payload = _llm_extract_text(
            source_text,
            document_kind=document_kind,
            settings=cfg,
        )
        method = "llm"
    except LLMUnavailable as exc:
        warnings.append(f"AI extract unavailable ({exc.message}); used local pattern matching.")
        logger.info("document_extract_llm_skipped err=%s", exc.message)
    except Exception as exc:
        warnings.append(f"AI extract failed ({exc}); used local pattern matching.")
        logger.warning("document_extract_llm_failed err=%s", exc)

    merged = _merge_extract(heuristic, ai_payload, document_kind=document_kind)
    merged_warnings = list(merged.get("warnings") or []) + warnings
    if not any(
        [
            merged.get("labs"),
            merged.get("medications"),
            (merged.get("note") or "").strip(),
            (merged.get("chief_complaint") or "").strip(),
            merged.get("diagnoses"),
        ]
    ):
        # Always keep a truncated source snippet so staff can still paste/review.
        merged["note"] = source_text[:8000]
        merged_warnings.append(
            "Could not confidently structure fields; source text placed in the visit note for review."
        )

    return _to_response(
        merged,
        method=method,
        media_kind=pulled.media_kind,
        filename=filename,
        page_count=pulled.page_count,
        source_excerpt=source_text[:2000],
        warnings=merged_warnings,
    )


def _llm_extract_text(
    text: str,
    *,
    document_kind: DocKind,
    settings: Settings,
) -> dict[str, Any]:
    if settings.external_llm_phi_blocked():
        # Still allow ollama/local; build_llm will block cloud PHI.
        pass
    prompt = (
        f"Document hint: {document_kind}.\n"
        "Extract labs, medications, diagnoses, vitals, and note sections from SOURCE.\n"
        f"SOURCE:\n{text[:12000]}"
    )
    last_err: Exception | None = None
    for name in settings.llm_provider_chain():
        try:
            provider = build_llm(settings, name)
            if getattr(provider, "name", "") == "local":
                # Local provider has no generative JSON path — skip to heuristic.
                continue
            raw = provider.complete_report(prompt, [_EXTRACT_SYSTEM])
            return _parse_json(raw)
        except (LLMUnavailable, ValueError, json.JSONDecodeError) as exc:
            last_err = exc
            continue
    if last_err is not None:
        raise LLMUnavailable(str(last_err)) from last_err
    raise LLMUnavailable("No generative LLM available for document extract.")


def _try_vision_extract(
    *,
    data: bytes,
    content_type: str,
    filename: str,
    document_kind: DocKind,
    settings: Settings,
) -> DocumentExtractResponse | None:
    if settings.external_llm_phi_blocked():
        return None
    b64 = base64.b64encode(data).decode("ascii")
    mime = content_type.split(";")[0].strip().lower() or "image/jpeg"
    if mime == "image/jpg":
        mime = "image/jpeg"
    user_text = (
        f"Document hint: {document_kind}. Filename: {filename or 'upload'}. "
        "Read the image and extract structured clinical fields as JSON."
    )
    for name in settings.llm_provider_chain():
        if name == "openai" and settings.openai_api_key.strip():
            try:
                raw = _openai_vision(settings, mime=mime, b64=b64, user_text=user_text)
                payload = _parse_json(raw)
                return _to_response(
                    payload,
                    method="llm_vision",
                    media_kind="image",
                    filename=filename,
                    page_count=1,
                    source_excerpt="",
                    warnings=["Extracted from image via OpenAI vision — review before saving."],
                )
            except Exception as exc:
                logger.info("openai_vision_extract_failed err=%s", exc)
                continue
        if name == "gemini" and settings.gemini_api_key.strip():
            try:
                raw = _gemini_vision(settings, mime=mime, b64=b64, user_text=user_text)
                payload = _parse_json(raw)
                return _to_response(
                    payload,
                    method="llm_vision",
                    media_kind="image",
                    filename=filename,
                    page_count=1,
                    source_excerpt="",
                    warnings=["Extracted from image via Gemini vision — review before saving."],
                )
            except Exception as exc:
                logger.info("gemini_vision_extract_failed err=%s", exc)
                continue
    return None


def _openai_vision(settings: Settings, *, mime: str, b64: str, user_text: str) -> str:
    model = settings.model_for_provider("openai")
    response = httpx.post(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
        },
        timeout=max(settings.llm_timeout_seconds, 60.0),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise LLMUnavailable("OpenAI vision returned empty content.")
    return content.strip()


def _gemini_vision(settings: Settings, *, mime: str, b64: str, user_text: str) -> str:
    model = settings.model_for_provider("gemini")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.gemini_api_key}"
    )
    response = httpx.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "contents": [
                {
                    "parts": [
                        {"text": f"{_EXTRACT_SYSTEM}\n\n{user_text}"},
                        {"inline_data": {"mime_type": mime, "data": b64}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0},
        },
        timeout=max(settings.llm_timeout_seconds, 60.0),
    )
    response.raise_for_status()
    payload = response.json()
    parts = payload["candidates"][0]["content"]["parts"]
    text = "".join(str(part.get("text") or "") for part in parts).strip()
    if not text:
        raise LLMUnavailable("Gemini vision returned empty content.")
    return text


def _heuristic_extract(text: str, *, document_kind: DocKind) -> dict[str, Any]:
    labs: list[dict[str, str]] = []
    meds: list[dict[str, str]] = []
    seen_labs: set[str] = set()
    seen_meds: set[str] = set()

    for match in _LAB_LINE.finditer(text):
        name = match.group(1).strip(" :-")
        if len(name) < 2:
            continue
        if document_kind == "prescription" and not _KNOWN_LABS.search(name):
            continue
        key = name.lower()
        if key in seen_labs:
            continue
        seen_labs.add(key)
        labs.append(
            {
                "test_name": name[:120],
                "value": match.group(2).strip()[:64],
                "unit": (match.group(3) or "").strip()[:64],
            }
        )

    for match in _KNOWN_LABS.finditer(text):
        name = match.group(1).strip()
        key = name.lower()
        if key in seen_labs:
            continue
        seen_labs.add(key)
        labs.append(
            {
                "test_name": name[:120],
                "value": match.group(2).strip()[:64],
                "unit": (match.group(3) or "").strip()[:64],
            }
        )

    if document_kind in {"auto", "prescription", "clinical_note"}:
        for match in _MED_LINE.finditer(text):
            name = match.group(1).strip()
            if len(name) < 3 or name.lower() in {
                "patient",
                "doctor",
                "date",
                "age",
                "sex",
                "prescription",
                "rx",
                "medicine",
                "medicines",
            }:
                continue
            key = name.lower()
            if key in seen_meds:
                continue
            seen_meds.add(key)
            dose = (match.group(2) or "").strip()
            freq = (match.group(3) or "").strip()
            meds.append(
                {
                    "name": name[:120],
                    "dose": dose[:120] or "as prescribed",
                    "frequency": freq[:64],
                    "route": "",
                    "status": "active",
                }
            )

    kind = document_kind
    if kind == "auto":
        if labs and not meds:
            kind = "lab_report"
        elif meds and not labs:
            kind = "prescription"
        else:
            kind = "clinical_note"

    note = ""
    if labs or meds:
        note = "Extracted from uploaded document (review required).\n"
        if labs:
            note += "Labs:\n" + "\n".join(
                f"- {row['test_name']}: {row['value']} {row.get('unit') or ''}".rstrip()
                for row in labs
            )
        if meds:
            note += ("\n" if labs else "") + "Medications:\n" + "\n".join(
                f"- {row['name']} {row.get('dose') or ''} {row.get('frequency') or ''}".rstrip()
                for row in meds
            )

    return {
        "document_kind": kind,
        "note": note.strip(),
        "labs": labs[:40],
        "medications": meds[:40],
        "diagnoses": [],
        "vitals": [],
        "chief_complaint": "",
        "history_of_present_illness": "",
        "assessment_and_plan": "",
        "procedure": "",
        "warnings": [],
    }


def _merge_extract(
    heuristic: dict[str, Any],
    ai_payload: dict[str, Any] | None,
    *,
    document_kind: DocKind,
) -> dict[str, Any]:
    if not ai_payload:
        return heuristic
    out = dict(heuristic)
    for key in (
        "document_kind",
        "chief_complaint",
        "history_of_present_illness",
        "assessment_and_plan",
        "note",
        "procedure",
    ):
        value = ai_payload.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    if document_kind != "auto" and document_kind in {
        "lab_report",
        "prescription",
        "clinical_note",
    }:
        out["document_kind"] = document_kind

    ai_labs = _coerce_labs(ai_payload.get("labs"))
    ai_meds = _coerce_meds(ai_payload.get("medications"))
    if ai_labs:
        out["labs"] = ai_labs
    if ai_meds:
        out["medications"] = ai_meds
    out["diagnoses"] = _coerce_dx(ai_payload.get("diagnoses")) or heuristic.get("diagnoses") or []
    out["vitals"] = _coerce_vitals(ai_payload.get("vitals")) or heuristic.get("vitals") or []
    warns = ai_payload.get("warnings")
    if isinstance(warns, list):
        out["warnings"] = [str(item) for item in warns if str(item).strip()][:12]
    return out


def _coerce_labs(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("test_name") or item.get("name") or "").strip()
        value = str(item.get("value") or "").strip()
        if not name or not value:
            continue
        rows.append(
            {
                "test_name": name[:120],
                "value": value[:64],
                "unit": str(item.get("unit") or "").strip()[:64],
            }
        )
    return rows


def _coerce_meds(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        status = str(item.get("status") or "active").strip().lower()
        if status not in {"active", "discontinued"}:
            status = "active"
        rows.append(
            {
                "name": name[:120],
                "dose": str(item.get("dose") or "as prescribed").strip()[:120] or "as prescribed",
                "frequency": str(item.get("frequency") or "").strip()[:64],
                "route": str(item.get("route") or "").strip()[:64],
                "status": status,
            }
        )
    return rows


def _coerce_dx(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        display = str(item.get("display") or item.get("name") or "").strip()
        if not display:
            continue
        rows.append({"display": display[:200], "code": str(item.get("code") or "").strip()[:32]})
    return rows


def _coerce_vitals(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    for item in raw[:40]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "").strip()
        if not name or not value:
            continue
        rows.append(
            {
                "name": name[:64],
                "value": value[:64],
                "unit": str(item.get("unit") or "").strip()[:32],
            }
        )
    return rows


def _to_response(
    payload: dict[str, Any],
    *,
    method: str,
    media_kind: str,
    filename: str,
    page_count: int,
    source_excerpt: str,
    warnings: list[str],
) -> DocumentExtractResponse:
    labs = [
        OpdLabIn(test_name=row["test_name"], value=row["value"], unit=row.get("unit") or "")
        for row in _coerce_labs(payload.get("labs"))
    ]
    meds = [
        OpdMedicationIn(
            name=row["name"],
            dose=row.get("dose") or "as prescribed",
            frequency=row.get("frequency") or "",
            route=row.get("route") or "",
            status=row.get("status") or "active",  # type: ignore[arg-type]
        )
        for row in _coerce_meds(payload.get("medications"))
    ]
    diagnoses = [
        OpdDiagnosisIn(display=row["display"], code=row.get("code") or "")
        for row in _coerce_dx(payload.get("diagnoses"))
    ]
    vitals = [
        OpdVitalIn(name=row["name"], value=row["value"], unit=row.get("unit") or "")
        for row in _coerce_vitals(payload.get("vitals"))
    ]
    kind = str(payload.get("document_kind") or "unknown")
    if kind not in {"lab_report", "prescription", "clinical_note", "unknown"}:
        kind = "unknown"
    note = str(payload.get("note") or "").strip()
    if not note and (labs or meds):
        note = "Extracted from uploaded document (review required)."
    return DocumentExtractResponse(
        document_kind=kind,  # type: ignore[arg-type]
        extraction_method=method,  # type: ignore[arg-type]
        media_kind=media_kind,  # type: ignore[arg-type]
        filename=filename or None,
        page_count=page_count,
        chief_complaint=str(payload.get("chief_complaint") or "").strip()[:500],
        history_of_present_illness=str(payload.get("history_of_present_illness") or "").strip()[
            :8000
        ],
        assessment_and_plan=str(payload.get("assessment_and_plan") or "").strip()[:8000],
        note=note[:20000],
        procedure=str(payload.get("procedure") or "").strip()[:200],
        diagnoses=diagnoses,
        labs=labs,
        medications=meds,
        vitals=vitals,
        source_excerpt=source_excerpt[:2000],
        warnings=warnings[:12],
        disclaimer=(
            "AI-assisted field extraction for chart prep only. "
            "Review every value before saving. Not for clinical use."
        ),
    )


# Re-export for tests.
__all__ = ["extract_clinical_document", "ExtractedText"]
