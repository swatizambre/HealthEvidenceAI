"""Synthetic patient read APIs with patient-record isolation."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    enforce_patient_access,
    get_db,
    get_principal,
    patient_list_scope,
    require_any_role,
)
from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import ROLES_CHART_READ
from app.schemas.api import (
    DocumentListResponse,
    LifelongSummaryResponse,
    PatientDetail,
    PatientEssentialsResponse,
    PatientListResponse,
    PatientPath,
    TimelineResponse,
)
from app.services.lifelong import get_lifelong_summary
from app.services.org_scope import care_team_org_filter_id
from app.services.records import (
    get_patient_detail,
    get_patient_essentials,
    get_patient_timeline,
    list_patient_documents,
    list_patient_summaries,
)

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=PatientListResponse)
def list_patients(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> PatientListResponse:
    scoped = patient_list_scope(request)
    if scoped:
        detail = get_patient_detail(db, scoped)
        from app.schemas.api import PatientSummary

        return PatientListResponse(
            patients=[
                PatientSummary(
                    patient_id=detail.patient_id,
                    synthetic_name=detail.demographics.synthetic_name,
                    date_of_birth=detail.demographics.date_of_birth,
                    sex=detail.demographics.sex,
                    conditions=list(detail.conditions),
                )
            ],
            total=1,
        )
    org_id = care_team_org_filter_id(db, get_principal(request))
    return list_patient_summaries(db, offset=offset, limit=limit, query=q, org_id=org_id)


@router.get("/{patient_id}", response_model=PatientDetail)
def get_patient(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> PatientDetail:
    enforce_patient_access(request, patient_id, db, action="chart_read")
    return get_patient_detail(db, patient_id)


@router.get("/{patient_id}/essentials", response_model=PatientEssentialsResponse)
def get_essentials(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> PatientEssentialsResponse:
    enforce_patient_access(request, patient_id, db, action="essentials_read")
    return get_patient_essentials(db, patient_id)


@router.get("/{patient_id}/timeline", response_model=TimelineResponse)
def get_timeline(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> TimelineResponse:
    enforce_patient_access(request, patient_id, db, action="timeline_read")
    return get_patient_timeline(db, patient_id)


@router.get("/{patient_id}/lifelong", response_model=LifelongSummaryResponse)
def get_lifelong(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> LifelongSummaryResponse:
    """Cross-facility lifelong history — self for patients; care-team for assigned charts."""
    enforce_patient_access(request, patient_id, db, action="lifelong_read")
    return get_lifelong_summary(db, patient_id)


@router.get("/{patient_id}/documents", response_model=DocumentListResponse)
def get_patient_documents(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> DocumentListResponse:
    enforce_patient_access(request, patient_id, db, action="documents_list")
    return list_patient_documents(db, patient_id)

