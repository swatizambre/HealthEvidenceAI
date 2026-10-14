"""HTTP facade for healthcare MCP tools + catalog."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import enforce_patient_access, get_db, require_care_team
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ensure_senior_hitl
from app.core.exceptions import AppError
from app.core.safety import PROTOTYPE_BANNER
from app.mcp.tools import TOOL_PERMISSIONS, call_tool, list_tool_names
from app.schemas.api import (
    McpToolCatalogResponse,
    McpToolInvokeRequest,
    McpToolInvokeResponse,
    McpToolOut,
    PatientPath,
    ToolPatientSummaryResponse,
)
from app.services.audit import record_audit
from app.services.disorders import clinical_conditions

router = APIRouter(prefix="/tools", tags=["tools"])

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_patient_record": "Load demographics and chart counts for a patient (MCP).",
    "get_patient_timeline": "Return chronological clinical events for a patient.",
    "get_policy": "Fetch payer policy metadata for a procedure checklist.",
    "get_policy_criteria": "List structured prior-auth criteria for a policy.",
    "search_clinical_evidence": "Hybrid RAG search over the patient chart (citations).",
    "get_evidence_chunk": "Fetch a single evidence chunk by document/chunk id.",
    "create_human_review": "Open a human-in-the-loop review pause for AuthorizationAgent.",
}

_AGENT_FLEET = [
    "Orchestrator",
    "PolicyAgent",
    "ClinicalEvidenceAgent",
    "ImagingAgent",
    "EvidenceVerificationAgent",
    "AuthorizationAgent",
]

_PATIENT_ARG_TOOLS = frozenset(
    {
        "get_patient_record",
        "get_patient_timeline",
        "search_clinical_evidence",
        "create_human_review",
    }
)


@router.get("", response_model=McpToolCatalogResponse)
def catalog_tools(
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> McpToolCatalogResponse:
    """List MCP tools agents may call (care-team only)."""
    tools = [
        McpToolOut(
            name=name,
            permission=TOOL_PERMISSIONS[name],
            description=_TOOL_DESCRIPTIONS.get(name, "Healthcare MCP tool."),
            agents=_agents_for_tool(name),
        )
        for name in list_tool_names()
    ]
    return McpToolCatalogResponse(
        tools=tools,
        agents=list(_AGENT_FLEET),
        disclaimer=PROTOTYPE_BANNER,
    )


@router.post("/invoke", response_model=McpToolInvokeResponse)
def invoke_tool(
    payload: McpToolInvokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_care_team()),
) -> McpToolInvokeResponse:
    """Invoke an MCP tool under a named agent (permission-gated + patient/org scope)."""
    if payload.tool_name not in TOOL_PERMISSIONS:
        raise AppError("MCP_TOOL_UNKNOWN", f"Unknown tool: {payload.tool_name}", 404)
    arguments = dict(payload.arguments or {})
    # Client-supplied agent name cannot elevate privileges for senior sign-off tools.
    auth_mode = str(getattr(request.app.state.settings, "auth_mode", "") or "").strip().lower()
    auth_on = auth_mode not in {"", "none", "off", "disabled"}
    if payload.tool_name == "create_human_review":
        decision = str(arguments.get("decision") or "pending").strip().lower()
        if decision in {"acknowledged", "needs_documentation"}:
            if auth_on:
                ensure_senior_hitl(principal)
        else:
            # Opening a pause is fine for care team; final decisions are senior-only.
            arguments["decision"] = "pending"
        # Attribute the audit row to the authenticated senior/caller, not a generic label.
        arguments["actor"] = str(getattr(principal, "subject", None) or "care_team")[:64]
    patient_code = _patient_code_for_tool(db, payload.tool_name, arguments)
    if patient_code:
        enforce_patient_access(request, patient_code, db, action=f"mcp_{payload.tool_name}")
    elif payload.tool_name in _PATIENT_ARG_TOOLS:
        raise AppError(
            "MCP_ARGS_INVALID",
            f"{payload.tool_name} requires patient_id.",
            400,
        )
    try:
        result = call_tool(
            db,
            tool_name=payload.tool_name,
            agent=payload.agent,
            arguments=arguments,
        )
    except KeyError as exc:
        raise AppError("MCP_TOOL_UNKNOWN", str(exc), 404) from exc
    except TypeError as exc:
        raise AppError("MCP_ARGS_INVALID", f"Invalid tool arguments: {exc}", 400) from exc
    actor = str(getattr(principal, "subject", None) or "care_team")[:64]
    record_audit(
        db,
        action=f"mcp_tool_{payload.tool_name}",
        actor=actor,
        resource_type="patient" if patient_code else "mcp_tool",
        resource_id=(patient_code or payload.tool_name)[:64],
        status="allowed",
        detail=f"agent={payload.agent}",
    )
    return McpToolInvokeResponse(
        tool_name=payload.tool_name,
        agent=payload.agent,
        result=dict(result),
        disclaimer=PROTOTYPE_BANNER,
    )


@router.get("/patients/{patient_id}/summary", response_model=ToolPatientSummaryResponse)
def get_patient_summary(
    patient_id: PatientPath,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_care_team()),
) -> ToolPatientSummaryResponse:
    enforce_patient_access(request, patient_id, db, action="mcp_patient_summary")
    result = call_tool(
        db,
        tool_name="get_patient_record",
        agent="ClinicalEvidenceAgent",
        arguments={"patient_id": patient_id},
    )
    actor = str(getattr(principal, "subject", None) or "care_team")[:64]
    record_audit(
        db,
        action="mcp_tool_get_patient_record",
        actor=actor,
        resource_type="patient",
        resource_id=patient_id[:64],
        status="allowed",
        detail="agent=ClinicalEvidenceAgent;via=summary",
    )
    return ToolPatientSummaryResponse(
        patient_id=str(result["patient_id"]),
        conditions=clinical_conditions(list(result.get("conditions") or [])),
        medication_count=int(result.get("medication_count") or 0),
        lab_count=int(result.get("lab_count") or 0),
        note_count=int(result.get("note_count") or 0),
        disclaimer=str(result.get("disclaimer") or PROTOTYPE_BANNER),
    )


def _patient_code_for_tool(
    db: Session, tool_name: str, arguments: dict[str, Any]
) -> str | None:
    raw = arguments.get("patient_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    if tool_name == "get_evidence_chunk":
        chunk_id = str(arguments.get("chunk_id") or "").strip()
        if not chunk_id:
            return None
        return _patient_for_chunk(db, chunk_id)
    return None


def _patient_for_chunk(db: Session, chunk_id: str) -> str | None:
    from sqlalchemy import select

    from app.models import Document, DocumentChunk, Patient

    row = db.execute(
        select(Patient.patient_code)
        .join(Document, Document.patient_id == Patient.id)
        .join(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.chunk_code == chunk_id)
    ).scalar_one_or_none()
    return str(row).strip().upper() if row else None


def _agents_for_tool(name: str) -> list[str]:
    if name.startswith("get_policy"):
        return ["PolicyAgent", "Orchestrator"]
    if name.startswith("search_") or name.startswith("get_evidence"):
        return ["ClinicalEvidenceAgent", "EvidenceVerificationAgent"]
    if name == "create_human_review":
        return ["AuthorizationAgent"]
    if name.startswith("get_patient"):
        return ["Orchestrator", "ClinicalEvidenceAgent"]
    return ["Orchestrator"]
