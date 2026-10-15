"""Patient report library: upload CBC/CT PDFs and images, list, and preview originals."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    enforce_patient_access,
    enforce_patient_write,
    get_db,
    get_principal,
    require_any_role,
)
from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import ROLES_CHART_READ, linked_patient_id
from app.auth.rbac import ROLES_CHART_WRITE
from app.core.exceptions import AppError
from app.models.entities import Patient
from app.schemas.api import DocumentPath, PatientPath, ReportListResponse, ReportOut
from app.services import report_files
from app.services.records import require_patient

router = APIRouter(tags=["reports"])

_PATIENT_CODE = re.compile(r"^PAT-\d{6}$")


def _actor(request: Request) -> str:
    principal = get_principal(request)
    return str(getattr(principal, "subject", None) or "care-team")[:120]


@router.get("/patients/{patient_id}/reports", response_model=ReportListResponse)
def list_reports(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> ReportListResponse:
    enforce_patient_access(request, patient_id, db, action="reports_list")
    rows = report_files.list_patient_reports(db, patient_id)
    return ReportListResponse(
        patient_id=patient_id,
        reports=[ReportOut(**row) for row in rows],
    )


@router.post("/reports/upload", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def upload_report(
    request: Request,
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    document_kind: Literal[
        "auto", "lab_report", "imaging_report", "prescription", "clinical_note"
    ] = Form("auto"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_WRITE)),
) -> ReportOut:
    """Upload a CBC / CT / prescription file, extract text, attach original for preview."""
    code_raw = (patient_id or "").strip().upper()
    if not _PATIENT_CODE.fullmatch(code_raw):
        raise AppError("VALIDATION_ERROR", "patient_id must look like PAT-000001.", 422)
    scoped = enforce_patient_write(request, code_raw, db)
    code = scoped or code_raw
    linked = linked_patient_id(principal)
    if linked and linked != code:
        raise AppError("PATIENT_SCOPE_FORBIDDEN", "You can only upload to your own chart.", 403)
    require_patient(db, code)
    data = await file.read()
    payload = report_files.upload_patient_report(
        db,
        patient_code=code,
        data=data,
        filename=file.filename or "report.bin",
        content_type=file.content_type or "application/octet-stream",
        document_kind=document_kind,
        actor=_actor(request),
        settings=request.app.state.settings,
    )
    return ReportOut(**payload)


@router.post(
    "/documents/{document_id}/file",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def attach_document_file(
    document_id: DocumentPath,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_WRITE)),
) -> ReportOut:
    """Attach the original PDF/image to an existing chart document (e.g. after visit ingest)."""
    document = report_files.get_document_for_access(db, document_id)
    patient_code = ""
    if document.patient_id:
        patient = db.get(Patient, document.patient_id)
        if patient is None:
            raise AppError("PATIENT_NOT_FOUND", "Patient for this document was not found.", 404)
        patient_code = patient.patient_code
        enforce_patient_write(request, patient_code, db)
    data = await file.read()
    payload = report_files.attach_file_to_document(
        db,
        document_code=document_id,
        data=data,
        filename=file.filename or "report.bin",
        content_type=file.content_type or "application/octet-stream",
        actor=_actor(request),
        settings=request.app.state.settings,
    )
    return ReportOut(**payload)


@router.get("/documents/{document_id}/file")
def download_document_file(
    document_id: DocumentPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> FileResponse:
    document, file_row, path = report_files.resolve_document_file(db, document_id)
    if document.patient_id:
        patient = db.get(Patient, document.patient_id)
        if patient is not None:
            enforce_patient_access(request, patient.patient_code, db, action="document_file")
    return FileResponse(
        path,
        media_type=file_row.content_type or "application/octet-stream",
        filename=file_row.original_filename or path.name,
        content_disposition_type="inline",
    )
