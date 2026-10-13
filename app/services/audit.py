"""Append-only audit events for evidence-review actions.

Do not store full clinical note text in the audit trail.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_audit(
    session: Session,
    *,
    action: str,
    actor: str,
    resource_type: str,
    resource_id: str,
    status: str,
    detail: str = "",
) -> AuditEvent:
    event = AuditEvent(
        id=str(uuid4()),
        action=action,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        detail=detail[:500],
    )
    session.add(event)
    session.flush()
    return event


def record_audit_durable(
    session: Session | None,
    *,
    action: str,
    actor: str,
    resource_type: str,
    resource_id: str,
    status: str,
    detail: str = "",
) -> AuditEvent | None:
    """Commit an audit row on its own transaction so 403 rollbacks cannot erase it."""
    if session is None:
        return None
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    audit_session = factory()
    try:
        event = record_audit(
            audit_session,
            action=action,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            detail=detail,
        )
        audit_session.commit()
        return event
    except Exception:  # noqa: BLE001 — never block the forbid path
        audit_session.rollback()
        return None
    finally:
        audit_session.close()


def list_audit_events(
    session: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> tuple[list[AuditEvent], int]:
    """Newest-first audit export for admin compliance review."""
    filters = []
    if action:
        filters.append(AuditEvent.action == action.strip()[:64])
    if actor:
        filters.append(AuditEvent.actor == actor.strip()[:64])
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type.strip()[:64])
    if resource_id:
        filters.append(AuditEvent.resource_id == resource_id.strip()[:64])
    count_stmt = select(func.count()).select_from(AuditEvent)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int(session.scalar(count_stmt) or 0)
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc())
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.offset(max(offset, 0)).limit(min(max(limit, 1), 500))
    return list(session.scalars(stmt).all()), total
