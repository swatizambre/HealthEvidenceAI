"""Evidence review for a synthetic authorization case (LangGraph)."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.agents.review import resume_review, review_authorization
from app.agents.runs import load_run
from app.api.deps import (
    enforce_patient_access,
    get_db,
    get_principal,
    require_any_role,
    require_care_team,
)
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import (
    ROLE_ADMIN,
    ROLES_EVIDENCE_CHECK,
    ROLES_HITL,
    ROLES_PACKET_PREP,
    ensure_senior_hitl,
    principal_roles,
)
from app.core.exceptions import AppError, NotFoundError
from app.core.safety import DISCLAIMER
from app.db.repository import get_case_by_code, get_patient_by_code
from app.schemas.api import (
    AuditEventListResponse,
    AuditEventOut,
    AuthorizationCaseListResponse,
    AuthorizationReviewRequest,
    AuthorizationReviewResponse,
    CaseAssignRequest,
    CaseAssignResponse,
    HumanReviewResumeRequest,
    PacketPrepareRequest,
    PacketPrepareResponse,
)
from app.services.audit import list_audit_events, record_audit
from app.services.need_to_know import ensure_case_need_to_know
from app.services.org_scope import care_team_org_filter_id
from app.services.pack_export import export_case_pdf_bytes
from app.services.packet_prep import prepare_evidence_packet
from app.services.realtime import publish_desk_event
from app.services.records import list_authorization_cases

router = APIRouter(prefix="/authorization", tags=["authorization"])


def _patient_org_id(db: Session, patient_code: str | None) -> str | None:
    """Org of the chart behind a desk event, so SSE fan-out stays tenant-scoped."""
    if not patient_code:
        return None
    patient = get_patient_by_code(db, patient_code)
    return getattr(patient, "org_id", None) if patient is not None else None


@router.get("/cases", response_model=AuthorizationCaseListResponse)
def get_cases(
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> AuthorizationCaseListResponse:
    org_id = care_team_org_filter_id(db, get_principal(request))
    return list_authorization_cases(db, org_id=org_id)


@router.post("/prepare", response_model=PacketPrepareResponse)
def prepare_packet(
    payload: PacketPrepareRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> PacketPrepareResponse:
    """Build a readiness packet: ensure case, run checklist, return gaps + printable summary."""
    enforce_patient_access(request, payload.patient_id, db, action="packet_prepare")
    result = prepare_evidence_packet(db, payload)
    actor = getattr(principal, "subject", None) or "care-team"
    record_audit(
        db,
        action="evidence_pack_prepare",
        actor=str(actor)[:64],
        resource_type="authorization_case",
        resource_id=result.case_id,
        status="completed",
        detail=f"patient={result.patient_id};readiness={result.readiness_percent}",
    )
    publish_desk_event(
        "evidence_pack_prepare",
        org_id=_patient_org_id(db, result.patient_id),
        case_id=result.case_id,
        patient_id=result.patient_id,
        actor=str(actor),
        readiness_percent=result.readiness_percent,
    )
    return result


@router.post("/review", response_model=AuthorizationReviewResponse)
def review_case(
    payload: AuthorizationReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_EVIDENCE_CHECK)),
) -> AuthorizationReviewResponse:
    enforce_patient_access(request, payload.patient_id, db, action="evidence_review")
    if payload.case_id:
        case = get_case_by_code(db, payload.case_id)
        if case is not None:
            ensure_case_need_to_know(db, principal, case)
    return review_authorization(
        db,
        payload,
        auto_complete_human_review=False,
    )


@router.post("/review/{run_id}/resume", response_model=AuthorizationReviewResponse)
def resume_case(
    run_id: str,
    payload: HumanReviewResumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(*ROLES_HITL)),
) -> AuthorizationReviewResponse:
    # Admin alone cannot forge senior acknowledgment (require_any_role admin-bypass).
    auth_mode = str(getattr(request.app.state.settings, "auth_mode", "") or "").strip().lower()
    if auth_mode not in {"", "none", "off", "disabled"}:
        ensure_senior_hitl(principal)
    state = load_run(run_id, db)
    if state is None:
        raise NotFoundError("REVIEW_RUN_NOT_FOUND", "Review run was not found.")
    patient_id = str(state.get("patient_id") or "").strip()
    if patient_id:
        enforce_patient_access(request, patient_id, db, action="hitl_resume")
    case_code = str(state.get("case_id") or "").strip()
    if case_code:
        case = get_case_by_code(db, case_code)
        if case is not None:
            ensure_case_need_to_know(db, principal, case)
    result = resume_review(db, run_id, payload)
    actor = getattr(principal, "subject", None) or "senior-clinician"
    decision = payload.decision
    reason = "confirm" if decision == "acknowledged" else "needs_documentation"
    case_id = result.case_id or str(state.get("case_id") or "")
    if case_id:
        assist = payload.senior_assist
        assist_bit = ""
        if assist is not None:
            assist_bit = (
                f";senior_assist=1;edited={int(bool(assist.edited))};"
                f"desk_action={assist.recommended_desk_action or 'n/a'}"
            )
        record_audit(
            db,
            action="evidence_pack_review",
            actor=str(actor)[:64],
            resource_type="authorization_case",
            resource_id=case_id,
            status="completed",
            detail=f"reason={reason};decision={decision};run={run_id}{assist_bit}",
        )
        publish_desk_event(
            "evidence_pack_review",
            org_id=_patient_org_id(db, patient_id or None),
            case_id=case_id,
            patient_id=patient_id or None,
            actor=str(actor),
            reason=reason,
            decision=decision,
        )
    return result


@router.post("/cases/{case_id}/assign", response_model=CaseAssignResponse)
def assign_case(
    case_id: str,
    payload: CaseAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_role(ROLE_ADMIN, *ROLES_PACKET_PREP)),
) -> CaseAssignResponse:
    """Assign a case to a desk subject (JWT subject) for Today my-queue."""
    case = get_case_by_code(db, case_id)
    if case is None:
        raise NotFoundError("CASE_NOT_FOUND", "Authorization case was not found.")
    from app.models import Patient

    patient = db.get(Patient, case.patient_id)
    patient_code = getattr(patient, "patient_code", None) if patient is not None else None
    if patient_code:
        enforce_patient_access(request, str(patient_code), db, action="case_assign")
    assignee = (payload.assigned_to or "").strip() or None
    # Non-admins may only assign to themselves.
    roles = principal_roles(principal)
    if ROLE_ADMIN not in roles:
        self_subject = str(getattr(principal, "subject", "") or "")
        if assignee and assignee != self_subject:
            raise AppError(
                "ASSIGN_FORBIDDEN",
                "Staff may only claim a case for themselves; ask an admin to reassign.",
                403,
            )
        if assignee is None:
            current = str(getattr(case, "assigned_to", "") or "")
            if current and current != self_subject:
                raise AppError(
                    "ASSIGN_FORBIDDEN",
                    "Only an admin can clear another clinician's assignment.",
                    403,
                )
    case.assigned_to = assignee
    db.flush()
    actor = str(getattr(principal, "subject", None) or "care-team")[:64]
    record_audit(
        db,
        action="case_assign",
        actor=actor,
        resource_type="authorization_case",
        resource_id=case.case_code,
        status="completed",
        detail=f"assigned_to={assignee or 'cleared'}",
    )
    publish_desk_event(
        "case_assign",
        org_id=getattr(patient, "org_id", None) if patient is not None else None,
        case_id=case.case_code,
        patient_id=str(patient_code) if patient_code else None,
        actor=actor,
        assigned_to=assignee,
    )
    return CaseAssignResponse(
        case_id=case.case_code,
        assigned_to=assignee,
        disclaimer=DISCLAIMER,
    )


@router.get("/cases/{case_id}/export.pdf")
def export_case_pdf(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> Response:
    """Download a minimal evidence-pack PDF (documentation readiness summary)."""
    case = get_case_by_code(db, case_id)
    if case is None:
        raise NotFoundError("CASE_NOT_FOUND", "Authorization case was not found.")
    from app.models import Patient

    patient = db.get(Patient, case.patient_id)
    patient_code = getattr(patient, "patient_code", None) if patient is not None else None
    if patient_code:
        enforce_patient_access(request, str(patient_code), db, action="pack_export")
    ensure_case_need_to_know(db, get_principal(request), case)
    pdf, filename = export_case_pdf_bytes(db, case_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/audit", response_model=AuditEventListResponse)
def case_audit_trail(
    case_id: str,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditEventListResponse:
    """Prep/review/assign trail for a case — care-team readable (no note bodies)."""
    case = get_case_by_code(db, case_id)
    if case is None:
        raise NotFoundError("CASE_NOT_FOUND", "Authorization case was not found.")
    rows, total = list_audit_events(
        db,
        limit=limit,
        offset=0,
        resource_type="authorization_case",
        resource_id=case.case_code,
    )
    return AuditEventListResponse(
        total=total,
        events=[
            AuditEventOut(
                event_id=row.id,
                action=row.action,
                actor=row.actor,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                status=row.status,
                detail=row.detail,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )

