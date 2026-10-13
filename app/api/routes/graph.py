"""Evidence graph built from an authorization review."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.agents.review import review_authorization
from app.api.deps import enforce_patient_access, get_db, require_care_team
from app.auth.oidc import AuthPrincipal
from app.core.safety import PROTOTYPE_BANNER
from app.schemas.api import (
    AuthorizationReviewRequest,
    EvidenceGraphResponse,
    GraphEdgeOut,
    GraphNodeOut,
)
from app.services.evidence_graph import build_evidence_graph
from app.services.permissions import require_tool_permission

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.post("/graph", response_model=EvidenceGraphResponse)
def evidence_graph(
    payload: AuthorizationReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    _principal: AuthPrincipal = Depends(require_care_team()),
) -> EvidenceGraphResponse:
    require_tool_permission("AuthorizationAgent", "read", "evidence")
    enforce_patient_access(request, payload.patient_id, db, action="evidence_graph")
    review = review_authorization(db, payload, auto_complete_human_review=False)
    graph = build_evidence_graph(review)
    return EvidenceGraphResponse(
        nodes=[GraphNodeOut(id=node.id, type=node.type, label=node.label) for node in graph.nodes],
        edges=[
            GraphEdgeOut(source=edge.source, target=edge.target, type=edge.type)
            for edge in graph.edges
        ],
        disclaimer=PROTOTYPE_BANNER,
    )

