"""Patient-owned emergency card, shares, family stubs + doctor brief helpers."""

from __future__ import annotations

from typing import Any

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
    EmergencyAlertListResponse,
    EmergencyAlertOut,
    EmergencyCardOut,
    EmergencyCardPatch,
    EmergencyPlaceIn,
    EmergencyPublicOut,
    RecordShareCreate,
    RecordShareListResponse,
    RecordShareOut,
    RecordSharePublicOut,
    SafetyChecksResponse,
)
from app.services import (
    abdm_stub,
    doctor_view,
    emergency_access,
    patient_record_share,
    safety_checks,
)
from app.services.records import require_patient

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


def _own_card(db: Session, code: str, payload: dict[str, Any]) -> EmergencyCardOut:
    """Owner's card plus the QR link and alert setting (never sent to other viewers)."""
    link = emergency_access.link_payload(db, require_patient(db, code))
    return EmergencyCardOut(**{**payload, **link})


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
    card = _own_card(db, code, payload)
    db.commit()
    return card


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
    card = _own_card(db, code, payload)
    db.commit()
    return card


@router.post("/me/emergency-card/rotate-link", response_model=EmergencyCardOut)
def rotate_my_emergency_link(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> EmergencyCardOut:
    """New QR link; printed cards and saved copies with the old one stop working."""
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    emergency_access.rotate_public_token(db, code, actor=_actor(request))
    payload = patient_record_share.emergency_card_payload(
        db, code, actor=_actor(request), record_view=False
    )
    card = _own_card(db, code, payload)
    db.commit()
    return card


@router.get("/me/emergency-alerts", response_model=EmergencyAlertListResponse)
def list_my_emergency_alerts(
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> EmergencyAlertListResponse:
    """Openings of my card, and of cards of family who listed me."""
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    rows = emergency_access.list_alerts(db, code)
    return EmergencyAlertListResponse(alerts=[EmergencyAlertOut(**row) for row in rows])


@router.post("/me/emergency-alerts/{event_id}/ack", response_model=EmergencyAlertOut)
def acknowledge_my_emergency_alert(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role("patient")),
) -> EmergencyAlertOut:
    code = _self_patient_code(request, principal)
    enforce_patient_access(request, code, db)
    row = emergency_access.acknowledge(db, code, event_id, actor=_actor(request))
    db.commit()
    return EmergencyAlertOut(**row)


@router.get("/emergency/{token}", response_model=EmergencyPublicOut)
def open_emergency_card(token: str, request: Request, db: Session = Depends(get_db)) -> EmergencyPublicOut:
    """Public: the emergency summary behind a card's QR code. Each opening alerts the family."""
    payload = emergency_access.open_public_card(
        db, token, user_agent=request.headers.get("user-agent", "")
    )
    db.commit()
    return EmergencyPublicOut(**payload)


@router.post("/emergency/{token}/events/{event_id}/place", response_model=EmergencyAlertOut)
def add_emergency_place(
    token: str, event_id: str, body: EmergencyPlaceIn, db: Session = Depends(get_db)
) -> EmergencyAlertOut:
    """Public: the person who opened the card can tell the family where the patient is."""
    row = emergency_access.add_place(
        db,
        token,
        event_id,
        place_note=body.place_note,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    db.commit()
    return EmergencyAlertOut(**{**row, "whose": ""})


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
    return RecordShareListResponse(
        shares=[RecordShareOut(**item) for item in patient_record_share.list_shares(db, code)]
    )


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


@router.get("/patients/{patient_id}/safety-checks", response_model=SafetyChecksResponse)
def patient_safety_checks(
    patient_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*sorted(ROLES_CHART_READ))),
) -> SafetyChecksResponse:
    """Cross-hospital checks: allergy vs medicine, same medicine twice, test not repeated."""
    del principal
    enforce_patient_access(request, patient_id, db)
    return SafetyChecksResponse(**safety_checks.run_safety_checks(db, patient_id))


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
