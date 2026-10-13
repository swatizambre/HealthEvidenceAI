"""Security, permission inspection, and break-glass (production RBAC path)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLE_ADMIN
from app.core.exceptions import AppError
from app.core.safety import DISCLAIMER
from app.db.repository import get_patient_by_code
from app.schemas.api import (
    BreakGlassRequest,
    BreakGlassResponse,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PromptInspectRequest,
    PromptInspectResponse,
)
from app.services.audit import record_audit
from app.services.break_glass import issue_ticket
from app.services.permissions import authorize_tool
from app.services.prompt_guard import inspect_retrieved_content

router = APIRouter(prefix="/security", tags=["security"])


@router.post("/permissions/check", response_model=PermissionCheckResponse)
def check_permission(payload: PermissionCheckRequest) -> PermissionCheckResponse:
    decision = authorize_tool(payload.agent, payload.action, payload.resource)
    return PermissionCheckResponse(
        allowed=decision.allowed,
        agent=decision.agent,
        action=decision.action,
        resource=decision.resource,
        reason=decision.reason,
    )


@router.post("/prompt/inspect", response_model=PromptInspectResponse)
def inspect_prompt(payload: PromptInspectRequest) -> PromptInspectResponse:
    result = inspect_retrieved_content(payload.content)
    return PromptInspectResponse(
        safe=result.safe,
        findings=list(result.findings),
        labeled_content=result.labeled_content,
    )


@router.post("/break-glass", response_model=BreakGlassResponse)
def break_glass_access(
    payload: BreakGlassRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(ROLE_ADMIN)),
) -> BreakGlassResponse:
    """Admin emergency chart access — ticket required for cross-org opens (enforced expiry)."""
    principal = get_principal(request)
    if principal is None:
        raise AppError("OIDC_UNAUTHORIZED", "Bearer token required.", 401)
    patient = get_patient_by_code(db, payload.patient_id)
    if patient is None:
        raise AppError("PATIENT_NOT_FOUND", "Patient was not found.", 404)
    reason = payload.reason.strip()[:500]
    ticket = issue_ticket(
        patient_id=payload.patient_id,
        actor=principal.subject[:64],
        reason=reason,
        ttl_seconds=3600,
    )
    record_audit(
        db,
        action="break_glass",
        actor=principal.subject[:64],
        resource_type="patient",
        resource_id=payload.patient_id,
        status="granted",
        detail=f"ticket={ticket.ticket_id};expires_at={int(ticket.expires_at)};reason={reason}",
    )
    return BreakGlassResponse(
        break_glass_id=ticket.ticket_id,
        patient_id=payload.patient_id,
        actor=principal.subject,
        reason=reason,
        expires_in_seconds=max(0, int(ticket.expires_at - time.time())),
        disclaimer=DISCLAIMER,
    )
