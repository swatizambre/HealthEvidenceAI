"""Named tool permissions enforced outside the language model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.exceptions import AppError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

PATIENT_READ = "PATIENT_READ"
POLICY_READ = "POLICY_READ"
EVIDENCE_SEARCH = "EVIDENCE_SEARCH"
EVIDENCE_READ = "EVIDENCE_READ"
HUMAN_REVIEW_CREATE = "HUMAN_REVIEW_CREATE"
REVIEW_WRITE = "REVIEW_WRITE"

# Action/resource pairs resolve to named permissions.
_ACTION_RESOURCE_MAP: dict[tuple[str, str], str] = {
    ("read", "clinical_notes"): PATIENT_READ,
    ("read", "labs"): PATIENT_READ,
    ("read", "medications"): PATIENT_READ,
    ("read", "patient_summary"): PATIENT_READ,
    ("read", "claims"): PATIENT_READ,
    ("read", "imaging"): PATIENT_READ,
    ("read", "imaging_metadata"): PATIENT_READ,
    ("read", "policies"): POLICY_READ,
    ("read", "evidence"): EVIDENCE_SEARCH,
    ("write", "review_draft"): REVIEW_WRITE,
    ("write", "human_review"): HUMAN_REVIEW_CREATE,
}

AGENT_PERMISSIONS: dict[str, set[str]] = {
    "ClinicalEvidenceAgent": {PATIENT_READ, EVIDENCE_SEARCH, EVIDENCE_READ},
    "PolicyAgent": {POLICY_READ, EVIDENCE_SEARCH, EVIDENCE_READ},
    "EvidenceVerificationAgent": {
        PATIENT_READ,
        POLICY_READ,
        EVIDENCE_SEARCH,
        EVIDENCE_READ,
        REVIEW_WRITE,
    },
    "AuthorizationAgent": {
        PATIENT_READ,
        POLICY_READ,
        EVIDENCE_SEARCH,
        EVIDENCE_READ,
        REVIEW_WRITE,
        HUMAN_REVIEW_CREATE,
    },
    "ImagingAgent": {PATIENT_READ, EVIDENCE_READ},
    "CriticAgent": {
        PATIENT_READ,
        POLICY_READ,
        EVIDENCE_SEARCH,
        EVIDENCE_READ,
        REVIEW_WRITE,
    },
    "PathwayAgent": {
        PATIENT_READ,
        POLICY_READ,
        EVIDENCE_READ,
        REVIEW_WRITE,
    },
    "UnauthenticatedAgent": set(),
}


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    agent: str
    action: str
    resource: str
    permission: str
    reason: str


def resolve_permission(action: str, resource: str) -> str:
    mapped = _ACTION_RESOURCE_MAP.get((action, resource))
    if mapped:
        return mapped
    upper = resource.upper()
    if upper in {
        PATIENT_READ,
        POLICY_READ,
        EVIDENCE_SEARCH,
        EVIDENCE_READ,
        HUMAN_REVIEW_CREATE,
        REVIEW_WRITE,
    }:
        return upper
    return f"{action.upper()}:{resource}"


def authorize_permission(agent: str, permission: str) -> PermissionDecision:
    profile = AGENT_PERMISSIONS.get(agent)
    if profile is None:
        return PermissionDecision(
            allowed=False,
            agent=agent,
            action="permission",
            resource=permission,
            permission=permission,
            reason="Unknown agent.",
        )
    allowed = permission in profile
    return PermissionDecision(
        allowed=allowed,
        agent=agent,
        action="permission",
        resource=permission,
        permission=permission,
        reason="Authorized." if allowed else "Agent is not authorized for this permission.",
    )


def authorize_tool(agent: str, action: str, resource: str) -> PermissionDecision:
    permission = resolve_permission(action, resource)
    decision = authorize_permission(agent, permission)
    return PermissionDecision(
        allowed=decision.allowed,
        agent=agent,
        action=action,
        resource=resource,
        permission=permission,
        reason=decision.reason,
    )


def require_permission(
    agent: str,
    permission: str,
    *,
    session: Session | None = None,
) -> None:
    decision = authorize_permission(agent, permission)
    if decision.allowed:
        return
    if session is not None:
        from app.services.audit import record_audit

        record_audit(
            session,
            action="tool_permission_denied",
            actor=agent,
            resource_type="permission",
            resource_id=permission,
            status="denied",
            detail=decision.reason,
        )
    raise AppError("TOOL_PERMISSION_DENIED", decision.reason, 403)


def require_tool_permission(
    agent: str,
    action: str,
    resource: str,
    *,
    session: Session | None = None,
) -> None:
    permission = resolve_permission(action, resource)
    require_permission(agent, permission, session=session)
