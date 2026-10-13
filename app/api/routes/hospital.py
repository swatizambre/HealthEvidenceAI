"""Hospital interface pipeline — inbound HIS/FHIR visits → chart → desk push."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import enforce_patient_write, get_db, get_principal, require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLES_CHART_WRITE, ROLES_PACKET_PREP
from app.schemas.api import (
    HospitalFhirPipelineRequest,
    HospitalHisPipelineRequest,
    HospitalPipelineRunOut,
    HospitalPipelineStatusOut,
    HospitalSimulateRequest,
    OpdFhirIngestRequest,
    OpdIngestRequest,
)
from app.services.hospital_pipeline import (
    pipeline_status,
    run_fhir_visit,
    run_his_visit,
    simulate_visit,
)
from app.services.org_scope import resolve_org_id

router = APIRouter(prefix="/hospital", tags=["hospital"])


def _org_id(request: Request, db: Session) -> str | None:
    principal = get_principal(request)
    if principal is None:
        return None
    return resolve_org_id(db, principal)


def _actor(request: Request) -> str:
    principal = get_principal(request)
    return str(getattr(principal, "subject", None) or "hospital-interface")


@router.get("/pipeline/status", response_model=HospitalPipelineStatusOut)
def get_pipeline_status(
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> HospitalPipelineStatusOut:
    """Recent hospital-feed runs and pipeline health (practice / synthetic)."""
    raw = pipeline_status(db)
    return HospitalPipelineStatusOut.model_validate(raw)


@router.post("/pipeline/visit", response_model=HospitalPipelineRunOut)
def post_his_visit(
    payload: HospitalHisPipelineRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_WRITE)),
) -> HospitalPipelineRunOut:
    """Interface-engine style visit webhook (HIS export fields)."""
    data = OpdIngestRequest.model_validate(payload.model_dump(exclude={"auto_prepare"}))
    scoped = enforce_patient_write(request, data.patient_id, db)
    if scoped:
        data = data.model_copy(update={"patient_id": scoped})
    result = run_his_visit(
        db,
        data,
        org_id=_org_id(request, db),
        actor=_actor(request),
        auto_prepare=payload.auto_prepare,
    )
    return HospitalPipelineRunOut.model_validate(result)


@router.post("/pipeline/fhir", response_model=HospitalPipelineRunOut)
def post_fhir_visit(
    payload: HospitalFhirPipelineRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_WRITE)),
) -> HospitalPipelineRunOut:
    """FHIR R4 Bundle webhook from hospital interface / EHR export."""
    from app.services.fhir_opd import fhir_bundle_to_opd_request

    fhir = OpdFhirIngestRequest.model_validate(payload.model_dump(exclude={"auto_prepare"}))
    # Same patient write-scope gate as HIS / OPD FHIR (patients forced to linked id).
    mapped = fhir_bundle_to_opd_request(fhir)
    scoped = enforce_patient_write(request, mapped.patient_id, db)
    if scoped:
        fhir = fhir.model_copy(update={"patient_id": scoped})
    result = run_fhir_visit(
        db,
        fhir,
        org_id=_org_id(request, db),
        actor=_actor(request),
        auto_prepare=payload.auto_prepare,
    )
    return HospitalPipelineRunOut.model_validate(result)


@router.post("/pipeline/simulate", response_model=HospitalPipelineRunOut)
def post_simulate(
    payload: HospitalSimulateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
    patient_id: str | None = Query(default=None, pattern=r"^PAT-\d{6}$"),
) -> HospitalPipelineRunOut:
    """One-click practice feed to prove chart + evidence pack + realtime desk."""
    target = patient_id or payload.patient_id
    enforce_patient_write(request, target, db)
    result = simulate_visit(
        db,
        patient_id=target,
        policy_id=payload.policy_id,
        org_id=_org_id(request, db),
        actor=_actor(request),
    )
    return HospitalPipelineRunOut.model_validate(result)
