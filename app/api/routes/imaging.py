"""Imaging analysis routes — MONAI-isolated path only."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLES_EVIDENCE_CHECK
from app.schemas.api import (
    ImagingAnalyzeRequest,
    ImagingAnalyzeResponse,
    ImagingCompareRequest,
    ImagingCompareResponse,
)
from app.services.imaging import build_image_analyzer
from app.services.permissions import require_tool_permission

router = APIRouter(prefix="/imaging", tags=["imaging"])


@router.post("/analyze", response_model=ImagingAnalyzeResponse)
def analyze_image(
    payload: ImagingAnalyzeRequest,
    request: Request,
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_EVIDENCE_CHECK)),
) -> ImagingAnalyzeResponse:
    """Non-diagnostic imaging features — care-team evidence check roles only."""
    require_tool_permission("ImagingAgent", "read", "imaging_metadata")
    result = build_image_analyzer(request.app.state.settings).analyze(
        payload.study_id,
        {"modality": payload.modality, "body_part": payload.body_part},
    )
    return ImagingAnalyzeResponse(
        study_id=result.study_id,
        observations=list(result.observations),
        confidence=result.confidence,
        human_review_required=result.human_review_required,
        disclaimer=result.disclaimer,
        backend=result.backend,
    )


@router.post("/compare", response_model=ImagingCompareResponse)
def compare_images(
    payload: ImagingCompareRequest,
    request: Request,
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_EVIDENCE_CHECK)),
) -> ImagingCompareResponse:
    """Non-diagnostic study compare — care-team evidence check roles only."""
    require_tool_permission("ImagingAgent", "read", "imaging_metadata")
    result = build_image_analyzer(request.app.state.settings).compare(
        payload.study_a,
        payload.study_b,
        payload.metadata_a,
        payload.metadata_b,
    )
    return ImagingCompareResponse(
        study_a=result.study_a,
        study_b=result.study_b,
        changed=list(result.changed),
        unchanged=list(result.unchanged),
        uncertain=list(result.uncertain),
        human_review_required=result.human_review_required,
        disclaimer=result.disclaimer,
        backend=result.backend,
    )
