"""Patient-owned emergency card, shares, family stubs + doctor brief helpers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import enforce_patient_access, get_db, get_principal, require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import ROLES_CHART_READ, is_patient_only, linked_patient_id
from app.core.exceptions import AppError
from app.schemas.api import (
    AbdmLinkRequest,
    AbdmStatusResponse,
    CareRelationshipCreate,
    CareRelationshipListResponse,
    CareRelationshipOut,
    ChartAskRequest,
    ChartAskResponse,
    DoctorBriefResponse,
    EmergencyCardOut,
    EmergencyCardPatch,
    RecordShareCreate,
    RecordShareListResponse,
    RecordShareOut,
    RecordSharePublicOut,
)
from app.services import abdm_stub, doctor_view, patient_record_share

router = APIRouter(tags=["me-record"])


def _actor(request: Request) -> str:
    principal = get_principal(request)
    subject = getattr(principal, "subject", None) if principal is not None else None
    return str(subject or "anonymous")[:120]


def _self_patient_code(request: Request, principal: AuthPrincipal) -> str:
    code = linked_patient_id(principal)
    if not code:
        raise AppError("PATIENT_LINK_REQUIRED", "Patient role token must include patient_id.", 400)
    if not is_patient_only(principal):
        raise AppError("FORBIDDEN", "Only the patient account owner can manage this resource.", 403)
    return code


@router.get("/me/emergency-card", response_model=EmergencyCardOut)
def get_my_emergency_card(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> EmergencyCardOut:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    payload = patient_record_share.emergency_card_payload(
        db, code, actor=_actor(request), record_view=True
    )
    db.commit()
    return EmergencyCardOut(**payload)


@router.patch("/me/emergency-card", response_model=EmergencyCardOut)
def patch_my_emergency_card(
    body: EmergencyCardPatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> EmergencyCardOut:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    payload = patient_record_share.update_emergency_profile(
        db, code, body.model_dump(exclude_unset=True), actor=_actor(request)
    )
    db.commit()
    return EmergencyCardOut(**payload)


@router.get("/patients/{patient_id}/emergency-card", response_model=EmergencyCardOut)
def get_patient_emergency_card(
    patient_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*sorted(ROLES_CHART_READ))),
) -> EmergencyCardOut:
    del principal
    enforce_patient_access(request, patient_id, db)
    payload = patient_record_share.emergency_card_payload(
        db, patient_id, actor=_actor(request), record_view=True
    )
    db.commit()
    return EmergencyCardOut(**payload)


@router.post("/me/shares", response_model=RecordShareOut, status_code=201)
def create_my_share(
    body: RecordShareCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> RecordShareOut:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    payload = patient_record_share.create_share(
        db,
        code,
        scopes=body.scopes,
        hours=body.hours,
        label=body.label or "",
        actor=_actor(request),
    )
    db.commit()
    return RecordShareOut(**payload)


@router.get("/me/shares", response_model=RecordShareListResponse)
def list_my_shares(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> RecordShareListResponse:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    return RecordShareListResponse(shares=patient_record_share.list_shares(db, code))


@router.delete("/me/shares/{share_id}", response_model=RecordShareOut)
def revoke_my_share(
    share_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> RecordShareOut:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    payload = patient_record_share.revoke_share(
        db, code, share_id, actor=_actor(request)
    )
    db.commit()
    return RecordShareOut(**payload)


@router.get("/share/{token}", response_model=RecordSharePublicOut)
def public_share(token: str, db: Session = Depends(get_db)) -> RecordSharePublicOut:
    payload = patient_record_share.resolve_public_share(db, token)
    db.commit()
    return RecordSharePublicOut(**payload)


@router.get("/me/family", response_model=CareRelationshipListResponse)
def list_my_family(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> CareRelationshipListResponse:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    rows = patient_record_share.list_care_relationships(db, code)
    return CareRelationshipListResponse(relationships=[CareRelationshipOut(**row) for row in rows])


@router.post("/me/family", response_model=CareRelationshipOut, status_code=201)
def create_my_family(
    body: CareRelationshipCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> CareRelationshipOut:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    payload = patient_record_share.create_care_relationship(
        db,
        code,
        related_display_name=body.related_display_name,
        relationship_type=body.relationship_type,
        related_patient_code=body.related_patient_code,
        access_level=body.access_level,
        actor=_actor(request),
    )
    db.commit()
    return CareRelationshipOut(**payload)


@router.get("/patients/{patient_id}/doctor-brief", response_model=DoctorBriefResponse)
def patient_doctor_brief(
    patient_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*sorted(ROLES_CHART_READ))),
) -> DoctorBriefResponse:
    del principal
    enforce_patient_access(request, patient_id, db)
    return DoctorBriefResponse(**doctor_view.doctor_brief_pack(db, patient_id))


@router.post("/patients/{patient_id}/chart-ask", response_model=ChartAskResponse)
def patient_chart_ask(
    patient_id: str,
    body: ChartAskRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*sorted(ROLES_CHART_READ))),
) -> ChartAskResponse:
    del principal
    enforce_patient_access(request, patient_id, db)
    return ChartAskResponse(**doctor_view.ask_chart_with_sources(db, patient_id, body.question))


@router.get("/abdm/status", response_model=AbdmStatusResponse)
def abdm_status() -> AbdmStatusResponse:
    return AbdmStatusResponse(**abdm_stub.abdm_status())


@router.post("/abdm/link")
def abdm_link(
    body: AbdmLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient", "admin")),
) -> dict:
    code = linked_patient_id(principal) or body.patient_id
    if not code:
        raise AppError("PATIENT_LINK_REQUIRED", "patient_id is required to link ABHA.", 400)
    enforce_patient_access(request, code, db)
    return abdm_stub.link_abha(db, code, abha_id=body.abha_id)
