"""Consent records and patient-rights APIs (DPDP Act 2023 / HIPAA access + amendment).

- /patients/{id}/consents — care team records; patient (self) and care team list / withdraw.
- /me/* — patient self-service: access log, data export, rights requests.
- /privacy/requests — facility privacy desk (staff / admin), org-scoped.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    enforce_patient_access,
    get_db,
    get_principal,
    require_any_role,
)
from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import ROLES_CHART_READ, is_patient_only, linked_patient_id
from app.auth.rbac import ROLES_CONSENT_RECORD, ROLES_PRIVACY_DESK
from app.core.exceptions import AppError, NotFoundError
from app.schemas.api import (
    AccessLogResponse,
    ConsentCreate,
    ConsentListResponse,
    ConsentOut,
    ConsentPath,
    ConsentRevokeRequest,
    DataSubjectRequestCreate,
    DataSubjectRequestListResponse,
    DataSubjectRequestOut,
    DataSubjectRequestPath,
    DataSubjectRequestResolve,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
    PatientExportResponse,
    PatientPath,
)
from app.services.audit import record_audit
from app.services.consent import (
    consent_list_response,
    consent_out,
    record_consent,
    revoke_consent,
)
from app.services.org_scope import care_team_org_filter_id, resolve_org_id
from app.services.patient_rights import (
    access_log,
    build_export,
    create_request,
    dsr_out,
    get_request_by_code,
    list_requests_for_org,
    list_requests_for_patient,
    require_request_patient,
    resolve_request,
)
from app.services.records import require_patient

router = APIRouter(tags=["privacy"])


def _actor(request: Request, fallback: str = "care-team") -> str:
    principal = get_principal(request)
    subject = getattr(principal, "subject", None) if principal is not None else None
    return str(subject or fallback)[:120]


def _principal_org(request: Request, db: Session) -> str | None:
    principal = get_principal(request)
    if principal is None:
        return None
    return resolve_org_id(db, principal)


def _caller_is_patient(request: Request) -> bool:
    return is_patient_only(get_principal(request))


def _self_patient_code(request: Request) -> str:
    """Patient-only self-service: the caller's own linked chart, never a path parameter."""
    principal = get_principal(request)
    if principal is None:
        raise AppError(
            "PATIENT_LINK_REQUIRED",
            "Sign in as a patient (token with a linked patient_id) to use /me endpoints.",
            403,
        )
    if not is_patient_only(principal):
        raise AppError(
            "RBAC_FORBIDDEN",
            "Self-service rights endpoints are for patient sign-ins. Care-team staff use "
            "/api/v1/privacy/requests.",
            403,
        )
    linked = linked_patient_id(principal)
    if not linked:
        raise AppError(
            "PATIENT_LINK_REQUIRED",
            "Patient sign-in requires a linked patient_id on the token.",
            403,
        )
    return linked


# --- Consent records -------------------------------------------------------------------


@router.post(
    "/patients/{patient_id}/consents",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_consent(
    patient_id: PatientPath,
    payload: ConsentCreate,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CONSENT_RECORD)),
) -> ConsentOut:
    """Record a consent captured at the desk (written form, e-consent, or witnessed verbal)."""
    enforce_patient_access(request, patient_id, db, action="consent_manage")
    patient = require_patient(db, patient_id)
    record = record_consent(
        db,
        patient,
        payload,
        recorded_by=_actor(request),
        org_id=_principal_org(request, db),
    )
    return consent_out(record, patient.patient_code)


@router.get("/patients/{patient_id}/consents", response_model=ConsentListResponse)
def list_consents(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> ConsentListResponse:
    """List consents (active and withdrawn). Patients may list only their own."""
    enforce_patient_access(request, patient_id, db, action="consent_list")
    patient = require_patient(db, patient_id)
    return consent_list_response(db, patient, mask_staff=_caller_is_patient(request))


@router.post(
    "/patients/{patient_id}/consents/{consent_id}/revoke",
    response_model=ConsentOut,
)
def withdraw_consent(
    patient_id: PatientPath,
    consent_id: ConsentPath,
    payload: ConsentRevokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> ConsentOut:
    """Withdraw consent — as easy as giving it (DPDP s.6(4)). Patients: own record only."""
    enforce_patient_access(request, patient_id, db, action="consent_manage")
    patient = require_patient(db, patient_id)
    record = revoke_consent(
        db,
        patient,
        consent_id,
        reason=payload.reason,
        revoked_by=_actor(request),
    )
    return consent_out(record, patient.patient_code, mask_staff=_caller_is_patient(request))


# --- Patient self-service ---------------------------------------------------------------


@router.get("/me/access-log", response_model=AccessLogResponse)
def my_access_log(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> AccessLogResponse:
    """Who accessed my record — accounting of disclosures / DPDP access summary."""
    code = _self_patient_code(request)
    require_patient(db, code)
    result = access_log(db, code, limit=limit, offset=offset)
    record_audit(
        db,
        action="access_log_read",
        actor=code,
        resource_type="patient",
        resource_id=code,
        status="allowed",
        detail="self",
    )
    return result


@router.get("/me/export", response_model=PatientExportResponse)
def my_export(
    request: Request,
    db: Session = Depends(get_db),
) -> PatientExportResponse:
    """Download a machine-readable copy of my own record (right of access / portability)."""
    code = _self_patient_code(request)
    patient = require_patient(db, code)
    export = build_export(db, patient)
    record_audit(
        db,
        action="data_export",
        actor=code,
        resource_type="patient",
        resource_id=code,
        status="allowed",
        detail=f"self;documents={len(export.documents)}",
    )
    return export


@router.post(
    "/me/requests",
    response_model=DataSubjectRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def create_my_request(
    payload: DataSubjectRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> DataSubjectRequestOut:
    """Raise a correction, erasure, grievance, or nominee request for my record."""
    code = _self_patient_code(request)
    patient = require_patient(db, code)
    row = create_request(db, patient, payload, submitted_by=code)
    return dsr_out(row, patient.patient_code, mask_staff=True)


@router.get("/me/requests", response_model=DataSubjectRequestListResponse)
def list_my_requests(
    request: Request,
    db: Session = Depends(get_db),
) -> DataSubjectRequestListResponse:
    code = _self_patient_code(request)
    patient = require_patient(db, code)
    return list_requests_for_patient(db, patient, mask_staff=True)


# --- Facility privacy desk --------------------------------------------------------------


@router.get("/privacy/requests", response_model=DataSubjectRequestListResponse)
def list_privacy_requests(
    request: Request,
    status_filter: DataSubjectRequestStatus | None = Query(default=None, alias="status"),
    request_type: DataSubjectRequestType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_PRIVACY_DESK)),
) -> DataSubjectRequestListResponse:
    """Org-scoped queue of patient rights requests for the grievance / privacy officer."""
    org_id = care_team_org_filter_id(db, get_principal(request))
    result = list_requests_for_org(
        db,
        org_id=org_id,
        status=status_filter,
        request_type=request_type,
        limit=limit,
        offset=offset,
    )
    record_audit(
        db,
        action="dsr_list",
        actor=_actor(request)[:64],
        resource_type="data_subject_request",
        resource_id="*",
        status="allowed",
        detail=f"count={len(result.requests)}",
    )
    return result


@router.post("/privacy/requests/{request_id}/resolve", response_model=DataSubjectRequestOut)
def resolve_privacy_request(
    request_id: DataSubjectRequestPath,
    payload: DataSubjectRequestResolve,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_PRIVACY_DESK)),
) -> DataSubjectRequestOut:
    """Mark in_review / resolved / rejected. Erasure closes with a retention outcome, never a delete."""
    row = get_request_by_code(db, request_id)
    if row is None:
        raise NotFoundError("DSR_NOT_FOUND", "Request was not found.")
    patient = require_request_patient(db, row)
    # Same org / break-glass gate as opening the chart.
    enforce_patient_access(request, patient.patient_code, db, action="dsr_review")
    updated = resolve_request(db, row, patient, payload, handled_by=_actor(request))
    return dsr_out(updated, patient.patient_code)
