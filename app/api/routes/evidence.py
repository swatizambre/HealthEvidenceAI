"""Hybrid RAG evidence search."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.llm import build_llm
from app.api.deps import enforce_patient_access, get_db, get_principal, require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.patient_scope import (
    ROLES_CHART_READ,
    ensure_care_team,
    is_patient_only,
    linked_patient_id,
)
from app.core.exceptions import AppError, RetrievalError
from app.schemas.api import EvidenceSearchRequest, EvidenceSearchResponse, SourceRef
from app.services.permissions import require_tool_permission
from app.services.prompt_guard import inspect_retrieved_content
from app.services.rag.pipeline import hybrid_search

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.post("/search", response_model=EvidenceSearchResponse)
def search_evidence(
    payload: EvidenceSearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_CHART_READ)),
) -> EvidenceSearchResponse:
    require_tool_permission("ClinicalEvidenceAgent", "read", "evidence", session=db)
    auth_off = request.app.state.settings.auth_mode.strip().lower() in {
        "",
        "none",
        "off",
        "disabled",
    }
    principal = get_principal(request)
    patient_code = payload.patient_id
    if not auth_off and is_patient_only(principal):
        linked = linked_patient_id(principal)
        if not linked:
            raise AppError(
                "PATIENT_LINK_REQUIRED",
                "Patient sign-in requires a linked patient_id on the token.",
                403,
            )
        if patient_code and patient_code != linked:
            raise AppError(
                "PATIENT_SCOPE_FORBIDDEN",
                "You can only access your own health record.",
                403,
            )
        patient_code = linked
    elif patient_code:
        enforce_patient_access(request, patient_code, db, action="evidence_search")
    elif not auth_off:
        # Unscoped evidence search is care-team only (minimum necessary).
        ensure_care_team(principal)
        from app.services.org_scope import org_scope_active

        if org_scope_active(request.app.state.settings):
            raise AppError(
                "PATIENT_ID_REQUIRED",
                "Evidence search requires patient_id when organization scope is enforced.",
                400,
            )

    try:
        hits = hybrid_search(
            db,
            query=payload.query,
            patient_code=patient_code,
            document_type=payload.document_type,
            limit=payload.limit,
            settings=request.app.state.settings,
        )
    except AppError:
        raise
    except SQLAlchemyError:
        raise
    except Exception as exc:
        raise RetrievalError() from exc
    labeled = [inspect_retrieved_content(hit.content).labeled_content for hit in hits]
    answer = build_llm(request.app.state.settings).complete(payload.query, labeled)
    return EvidenceSearchResponse(
        answer=answer,
        sources=[
            SourceRef(
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                document_type=hit.document_type,
                score=hit.score,
            )
            for hit in hits
        ],
    )

