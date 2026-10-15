"""Upload, list, and serve patient report files (CBC PDFs, CT reports, etc.)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, NotFoundError
from app.db.repository import list_documents_for_patient, next_public_code
from app.models.entities import Document, DocumentFile, ImagingStudy, LabResult
from app.services.document_extract import extract_clinical_document
from app.services.indexing import index_document
from app.services.records import require_patient

ReportKind = Literal["auto", "lab_report", "imaging_report", "prescription", "clinical_note"]

_MAX_BYTES = 15 * 1024 * 1024
_ALLOWED_SUFFIX = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".md"})
_IMAGING_HINT = re.compile(r"(?i)\b(ct|mri|x-?ray|ultrasound|usg|scan|radiolog|pet|mammogra)\b")


def _uploads_root(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    # Keep uploads beside the SQLite data dir when possible.
    root = Path("data") / "uploads"
    if "postgres" in (cfg.database_url or "").lower():
        root = Path("data") / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(name: str) -> str:
    base = Path(name or "report.bin").name
    cleaned = re.sub(r"[^A-Za-z0-9._\-]+", "_", base).strip("._") or "report.bin"
    return cleaned[:180]


def _now() -> datetime:
    return datetime.now(UTC)


def _resolve_doc_type(kind: ReportKind, filename: str, extracted_kind: str) -> str:
    if kind == "lab_report":
        return "lab_result"
    if kind == "imaging_report":
        return "radiology_report"
    if kind == "prescription":
        return "clinical_note"
    if kind == "clinical_note":
        return "clinical_note"
    # auto
    if extracted_kind == "lab_report":
        return "lab_result"
    if extracted_kind == "prescription":
        return "clinical_note"
    if _IMAGING_HINT.search(filename) or _IMAGING_HINT.search(extracted_kind):
        return "radiology_report"
    if extracted_kind == "clinical_note":
        return "clinical_note"
    return "investigation_report"


def _file_row(session: Session, document_id: str) -> DocumentFile | None:
    return session.scalar(select(DocumentFile).where(DocumentFile.document_id == document_id))


def upload_patient_report(
    session: Session,
    *,
    patient_code: str,
    data: bytes,
    filename: str,
    content_type: str,
    document_kind: ReportKind = "auto",
    actor: str = "care-team",
    settings: Settings | None = None,
) -> dict[str, Any]:
    if not data:
        raise AppError("VALIDATION_ERROR", "Empty file.", 422)
    if len(data) > _MAX_BYTES:
        raise AppError("VALIDATION_ERROR", "File too large (max 15 MB).", 422)
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in _ALLOWED_SUFFIX:
        raise AppError(
            "VALIDATION_ERROR",
            f"Unsupported file type {suffix}. Use PDF, PNG, JPG, WEBP, GIF, or TXT.",
            422,
        )

    patient = require_patient(session, patient_code)
    cfg = settings or get_settings()
    # Map imaging to lab_report/clinical for extract engine (it does not know imaging yet).
    extract_kind: Any = "auto"
    if document_kind == "imaging_report":
        extract_kind = "clinical_note"
    elif document_kind in {"lab_report", "prescription", "clinical_note", "auto"}:
        extract_kind = document_kind

    extracted = extract_clinical_document(
        data=data,
        filename=filename or "",
        content_type=content_type or "",
        document_kind=extract_kind,
        settings=cfg,
    )
    doc_type = _resolve_doc_type(
        document_kind, filename or "", str(extracted.document_kind or "unknown")
    )
    now = _now()
    text = (extracted.source_excerpt or extracted.note or "").strip()
    if not text and extracted.labs:
        text = "\n".join(
            f"{lab.test_name}: {lab.value} {lab.unit}".strip() for lab in extracted.labs[:40]
        )
    if not text:
        text = f"Uploaded report: {filename or 'file'} ({content_type or 'unknown type'})."

    document = Document(
        id=str(uuid4()),
        document_code=next_public_code(session, Document.document_code, "DOC"),
        patient_id=patient.id,
        document_type=doc_type,
        source=f"upload:{_safe_name(filename)}",
        content=text[:20000],
        document_metadata={
            "upload": True,
            "original_filename": _safe_name(filename),
            "content_type": (content_type or "application/octet-stream")[:120],
            "document_kind": document_kind,
            "extraction_method": extracted.extraction_method,
            "uploaded_by": actor[:120],
            "title": _safe_name(filename),
        },
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.flush()

    digest = hashlib.sha256(data).hexdigest()
    folder = _uploads_root(cfg) / patient.patient_code
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{document.document_code}_{_safe_name(filename)}"
    path = folder / stored_name
    path.write_bytes(data)

    file_row = DocumentFile(
        id=str(uuid4()),
        document_id=document.id,
        original_filename=_safe_name(filename),
        content_type=(content_type or "application/octet-stream")[:120],
        storage_path=str(path).replace("\\", "/"),
        byte_size=len(data),
        sha256=digest,
        created_at=now,
        updated_at=now,
    )
    session.add(file_row)

    # Chart rows so Labs / Imaging tabs populate.
    if doc_type == "lab_result" or extracted.labs:
        for lab in (extracted.labs or [])[:40]:
            session.add(
                LabResult(
                    id=str(uuid4()),
                    lab_code=next_public_code(session, LabResult.lab_code, "LAB"),
                    patient_id=patient.id,
                    document_id=document.id,
                    test_name=(lab.test_name or "Lab")[:120],
                    value=str(lab.value or "")[:64],
                    unit=str(lab.unit or "")[:64],
                    collected_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    if doc_type == "radiology_report" or document_kind == "imaging_report":
        modality = "CT" if re.search(r"(?i)\bct\b", filename or text) else "Imaging"
        if re.search(r"(?i)\bmri\b", filename or text):
            modality = "MRI"
        if re.search(r"(?i)\bx-?ray\b", filename or text):
            modality = "XR"
        if re.search(r"(?i)\bultrasound|usg\b", filename or text):
            modality = "US"
        session.add(
            ImagingStudy(
                id=str(uuid4()),
                imaging_code=next_public_code(session, ImagingStudy.imaging_code, "IMG"),
                patient_id=patient.id,
                document_id=document.id,
                modality=modality[:32],
                body_part="Report",
                studied_at=now,
                description=(extracted.note or text)[:2000],
                created_at=now,
                updated_at=now,
            )
        )

    index_document(session, document)
    session.flush()
    return report_out(session, document, patient.patient_code, extracted_summary=True)


def list_patient_reports(session: Session, patient_code: str) -> list[dict[str, Any]]:
    patient = require_patient(session, patient_code)
    docs = list_documents_for_patient(session, patient.id)
    # Prefer uploaded / investigation / radiology / lab docs; still include others with files.
    items: list[dict[str, Any]] = []
    for document in sorted(docs, key=lambda row: row.created_at, reverse=True):
        file_row = _file_row(session, document.id)
        meta = document.document_metadata or {}
        is_reportish = document.document_type in {
            "lab_result",
            "radiology_report",
            "investigation_report",
            "discharge_summary",
            "clinical_note",
        } or bool(meta.get("upload")) or file_row is not None
        if not is_reportish:
            continue
        items.append(report_out(session, document, patient.patient_code))
    return items


def report_out(
    session: Session,
    document: Document,
    patient_code: str,
    *,
    extracted_summary: bool = False,
) -> dict[str, Any]:
    file_row = _file_row(session, document.id)
    meta = document.document_metadata or {}
    title = str(meta.get("title") or meta.get("original_filename") or document.source)
    payload: dict[str, Any] = {
        "document_id": document.document_code,
        "patient_id": patient_code,
        "document_type": document.document_type,
        "title": title,
        "source": document.source,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "has_file": file_row is not None,
        "original_filename": (
            file_row.original_filename if file_row else str(meta.get("original_filename") or "")
        ),
        "content_type": (
            file_row.content_type if file_row else str(meta.get("content_type") or "")
        ),
        "byte_size": int(file_row.byte_size) if file_row else 0,
        "preview_kind": _preview_kind(file_row.content_type if file_row else ""),
        "content_excerpt": (document.content or "")[:400],
        "file_url": f"/api/v1/documents/{document.document_code}/file" if file_row else None,
    }
    if extracted_summary:
        payload["content"] = document.content
    return payload


def _preview_kind(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return "pdf"
    if ct.startswith("image/") or any(token in ct for token in ("png", "jpeg", "jpg", "webp", "gif")):
        return "image"
    if ct.startswith("text/") or "json" in ct:
        return "text"
    return "other"


def resolve_document_file(session: Session, document_code: str) -> tuple[Document, DocumentFile, Path]:
    document = session.scalar(select(Document).where(Document.document_code == document_code))
    if document is None:
        raise NotFoundError("DOCUMENT_NOT_FOUND", "Document was not found.")
    file_row = _file_row(session, document.id)
    if file_row is None:
        raise NotFoundError("FILE_NOT_FOUND", "No original file is attached to this document.")
    path = Path(file_row.storage_path)
    if not path.is_file():
        raise NotFoundError("FILE_MISSING", "Stored file is missing on disk.")
    return document, file_row, path


def get_document_for_access(session: Session, document_code: str) -> Document:
    document = session.scalar(select(Document).where(Document.document_code == document_code))
    if document is None:
        raise NotFoundError("DOCUMENT_NOT_FOUND", "Document was not found.")
    return document


def attach_file_to_document(
    session: Session,
    *,
    document_code: str,
    data: bytes,
    filename: str,
    content_type: str,
    actor: str = "care-team",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persist an original binary against an existing chart document."""
    if not data:
        raise AppError("VALIDATION_ERROR", "Empty file.", 422)
    if len(data) > _MAX_BYTES:
        raise AppError("VALIDATION_ERROR", "File too large (max 15 MB).", 422)
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in _ALLOWED_SUFFIX:
        raise AppError(
            "VALIDATION_ERROR",
            f"Unsupported file type {suffix}. Use PDF, PNG, JPG, WEBP, GIF, or TXT.",
            422,
        )
    document = get_document_for_access(session, document_code)
    if _file_row(session, document.id) is not None:
        raise AppError("FILE_EXISTS", "This document already has an attached file.", 409)
    if not document.patient_id:
        raise AppError("VALIDATION_ERROR", "Document is not linked to a patient chart.", 422)
    from app.models.entities import Patient

    patient = session.get(Patient, document.patient_id)
    if patient is None:
        raise NotFoundError("PATIENT_NOT_FOUND", "Patient was not found.")

    cfg = settings or get_settings()
    now = _now()
    digest = hashlib.sha256(data).hexdigest()
    folder = _uploads_root(cfg) / patient.patient_code
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{document.document_code}_{_safe_name(filename)}"
    path = folder / stored_name
    path.write_bytes(data)

    file_row = DocumentFile(
        id=str(uuid4()),
        document_id=document.id,
        original_filename=_safe_name(filename),
        content_type=(content_type or "application/octet-stream")[:120],
        storage_path=str(path).replace("\\", "/"),
        byte_size=len(data),
        sha256=digest,
        created_at=now,
        updated_at=now,
    )
    session.add(file_row)
    meta = dict(document.document_metadata or {})
    meta.update(
        {
            "upload": True,
            "original_filename": _safe_name(filename),
            "content_type": (content_type or "application/octet-stream")[:120],
            "attached_by": actor[:120],
            "title": meta.get("title") or _safe_name(filename),
        }
    )
    document.document_metadata = meta
    document.updated_at = now
    session.flush()
    return report_out(session, document, patient.patient_code)
