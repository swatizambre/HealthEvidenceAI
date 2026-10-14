"""India cashless pre-authorization (TPA) desk — docs/TPA_DESK_CONTRACT.md.

Org- and patient-scoped like the existing authorization routes, and audited. The
desk prepares paperwork and records what the insurer/TPA did; it never approves,
denies or submits anything to an insurer.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    enforce_patient_access,
    get_db,
    get_principal,
    require_any_role,
    require_care_team,
)
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLES_PACKET_PREP
from app.models import AuthorizationCase
from app.schemas.desk import (
    DeskCaseCreate,
    DeskCaseFields,
    DeskDischargeCheckResponse,
    DeskPreauthFormResponse,
    DeskStageRequest,
    DeskStatsResponse,
    DeskWorklistResponse,
    DeskWorkspaceResponse,
)
from app.services import tpa_desk
from app.services.audit import record_audit
from app.services.need_to_know import ensure_case_need_to_know
from app.services.org_scope import care_team_org_filter_id
from app.services.realtime import publish_desk_event

router = APIRouter(prefix="/desk", tags=["tpa-desk"])

CasePath = Annotated[str, Path(pattern=r"^PA-\d{6}$")]


def _actor(principal: AuthPrincipal | None) -> str:
    return str(getattr(principal, "subject", None) or "care-team")[:64]


def _scoped_case(
    request: Request, db: Session, case_id: str, *, action: str
) -> AuthorizationCase:
    """Load a case and enforce patient/org scope + need-to-know (same as /authorization)."""
    case = tpa_desk.require_case(db, case_id)
    patient = tpa_desk.case_patient(db, case)
    if patient is not None:
        enforce_patient_access(request, patient.patient_code, db, action=action)
    ensure_case_need_to_know(db, get_principal(request), case)
    return case


def _workspace(db: Session, case: AuthorizationCase) -> dict[str, Any]:
    return tpa_desk.build_workspace(db, case)


def _publish(db: Session, event: str, case: AuthorizationCase, actor: str, **extra: Any) -> None:
    patient = tpa_desk.case_patient(db, case)
    publish_desk_event(
        event,
        org_id=getattr(patient, "org_id", None) if patient is not None else None,
        case_id=case.case_code,
        patient_id=patient.patient_code if patient is not None else None,
        actor=actor,
        **extra,
    )


@router.get("/worklist", response_model=DeskWorklistResponse)
def desk_worklist(
    request: Request,
    stage: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> dict[str, Any]:
    """Cashless cases sorted by urgency: overdue first, then least time left, then oldest."""
    org_id = care_team_org_filter_id(db, get_principal(request))
    return tpa_desk.desk_worklist(
        db, org_id=org_id, stage=stage, q=q, limit=limit, offset=offset
    )


@router.get("/stats", response_model=DeskStatsResponse)
def desk_stats(
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> dict[str, Any]:
    org_id = care_team_org_filter_id(db, get_principal(request))
    return tpa_desk.desk_stats(db, org_id=org_id)


@router.post("/cases", response_model=DeskWorkspaceResponse, status_code=201)
def create_desk_case(
    payload: DeskCaseCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> dict[str, Any]:
    enforce_patient_access(request, payload.patient_id, db, action="desk_case_create")
    actor = _actor(principal)
    case = tpa_desk.create_case(db, payload.model_dump(), actor=actor)
    _publish(db, "desk_case_create", case, actor)
    return _workspace(db, case)


@router.get("/cases/{case_id}", response_model=DeskWorkspaceResponse)
def get_desk_case(
    case_id: CasePath,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_care_team()),
) -> dict[str, Any]:
    case = _scoped_case(request, db, case_id, action="desk_case_view")
    record_audit(
        db,
        action="desk_case_view",
        actor=_actor(principal),
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
    )
    return _workspace(db, case)


@router.patch("/cases/{case_id}", response_model=DeskWorkspaceResponse)
def update_desk_case(
    case_id: CasePath,
    payload: DeskCaseFields,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> dict[str, Any]:
    case = _scoped_case(request, db, case_id, action="desk_case_update")
    actor = _actor(principal)
    changed = tpa_desk.update_case(db, case, payload.model_dump(exclude_unset=True), actor=actor)
    if changed:
        _publish(db, "desk_case_update", case, actor, fields=changed)
    return _workspace(db, case)


@router.post("/cases/{case_id}/stage", response_model=DeskWorkspaceResponse)
def desk_stage_action(
    case_id: CasePath,
    payload: DeskStageRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> dict[str, Any]:
    """Record what happened on the insurer/TPA portal. Senior acknowledgment itself stays
    on POST /authorization/review/{run_id}/resume (senior-only)."""
    case = _scoped_case(request, db, case_id, action="desk_stage_action")
    actor = _actor(principal)
    stage = tpa_desk.apply_stage_action(
        db, case, payload.model_dump(exclude_none=True), actor=actor
    )
    _publish(db, "desk_stage_action", case, actor, action=payload.action, stage=stage)
    return _workspace(db, case)


@router.get("/cases/{case_id}/preauth-form", response_model=DeskPreauthFormResponse)
def desk_preauth_form(
    case_id: CasePath,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_care_team()),
) -> dict[str, Any]:
    from app.services.tpa_forms import preauth_form

    case = _scoped_case(request, db, case_id, action="desk_preauth_form")
    form = preauth_form(db, case)
    record_audit(
        db,
        action="desk_preauth_form_view",
        actor=_actor(principal),
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
        detail=f"missing_required={len(form['missing_required'])}",
    )
    return form


@router.get("/cases/{case_id}/discharge-check", response_model=DeskDischargeCheckResponse)
def desk_discharge_check(
    case_id: CasePath,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_care_team()),
) -> dict[str, Any]:
    from app.services.tpa_forms import discharge_check

    case = _scoped_case(request, db, case_id, action="desk_discharge_check")
    result = discharge_check(db, case)
    record_audit(
        db,
        action="desk_discharge_check",
        actor=_actor(principal),
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
        detail=f"status={result['status']}",
    )
    return result
