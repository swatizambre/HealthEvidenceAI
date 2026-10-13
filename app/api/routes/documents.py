"""Document ingestion and retrieval with patient-record isolation."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    enforce_patient_access,
    enforce_patient_write,
    get_db,
    get_principal,
    require_any_role,
    require_care_team,
)
from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import ROLES_CHART_READ, ensure_care_team, is_patient_only
from app.core.exceptions import AppError
from app.schemas.api import DocumentCreate, DocumentOut, DocumentPath
from app.services.ingestion import ingest_document
from app.services.records import get_document_detail

router = APIRouter(prefix="/documents", tags=["documents"])


def _auth_off(request: Request) -> bool:
    return request.app.state.settings.auth_mode.strip().lower() in {"", "none", "off", "disabled"}


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> DocumentOut:
    """Care-team document ingest only (patients use Visit note / OPD ingest)."""
    scoped = enforce_patient_write(request, payload.patient_id, db)
    data = payload.model_copy(update={"patient_id": scoped}) if scoped else payload
    return ingest_document(db, data)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: DocumentPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> DocumentOut:
    detail = get_document_detail(db, document_id)
    if detail.patient_id:
        enforce_patient_access(request, detail.patient_id, db, action="document_read")
        return detail
    principal = get_principal(request)
    if not _auth_off(request) and is_patient_only(principal):
        raise AppError(
            "PATIENT_SCOPE_FORBIDDEN",
            "You can only access your own health record.",
            403,
        )
    if not _auth_off(request):
        ensure_care_team(principal)
    return detail

