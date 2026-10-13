"""Admin audit export for pilot / compliance review."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLE_ADMIN
from app.schemas.api import AuditEventListResponse, AuditEventOut
from app.services.audit import list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=AuditEventListResponse)
def get_audit_events(
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(ROLE_ADMIN)),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=64),
    actor: str | None = Query(default=None, max_length=64),
) -> AuditEventListResponse:
    """List recent audit events (no clinical note bodies). Admin only."""
    rows, total = list_audit_events(
        db, limit=limit, offset=offset, action=action, actor=actor
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

