"""AI scope and grounded assists — decision-support only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import Field

from app.api.deps import require_any_role
from app.auth.oidc import AuthPrincipal
from app.auth.rbac import ROLES_HITL, ROLES_PACKET_PREP
from app.core.config import get_settings
from app.core.safety import DISCLAIMER
from app.schemas.api import APIModel, ResponseModel
from app.services.ai_assist import draft_gap_suggestion, senior_review_assist
from app.services.ai_scope import describe_ai_scope

router = APIRouter(prefix="/ai", tags=["ai"])


class GapDraftRequest(APIModel):
    label: str = Field(min_length=2, max_length=200)
    focus: str = Field(default="note", max_length=32)
    snippets: list[str] = Field(default_factory=list, max_length=5)


class GapDraftResponse(ResponseModel):
    draft_suggestion: str
    draft_source: str
    focus: str
    disclaimer: str


class SeniorReviewCriterionIn(APIModel):
    criterion: str = Field(min_length=2, max_length=400)
    status: str = Field(max_length=32)
    reason: str = Field(default="", max_length=800)


class SeniorReviewRequest(APIModel):
    patient_id: str = Field(pattern=r"^PAT-\d{6}$")
    case_id: str | None = Field(default=None, pattern=r"^PA-\d{6}$")
    procedure: str = Field(default="Evidence pack documentation", max_length=200)
    criteria: list[SeniorReviewCriterionIn] = Field(default_factory=list, max_length=40)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)
    contradictions: list[str] = Field(default_factory=list, max_length=12)
    critic_notes: list[str] = Field(default_factory=list, max_length=12)
    report_summary: str = Field(default="", max_length=2000)


class SeniorReviewFocusOut(ResponseModel):
    title: str
    detail: str
    severity: str = "moderate"


class SeniorReviewResponse(ResponseModel):
    briefing: str
    focus_items: list[SeniorReviewFocusOut]
    suggested_clinician_note: str
    recommended_desk_action: str
    recommended_desk_action_label: str
    source: str
    disclaimer: str


@router.get("/scope")
def get_ai_scope() -> dict[str, object]:
    """Public: where AI is used and what it must never decide."""
    return describe_ai_scope(get_settings())


@router.post("/gap-draft", response_model=GapDraftResponse)
def post_gap_draft(
    payload: GapDraftRequest,
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_PACKET_PREP)),
) -> GapDraftResponse:
    """On-demand visit-note coaching draft from chart cues (not a diagnosis)."""
    draft, source = draft_gap_suggestion(
        payload.label,
        payload.focus or "note",
        list(payload.snippets or [])[:5],
        use_llm=True,
    )
    return GapDraftResponse(
        draft_suggestion=draft,
        draft_source=source,
        focus=payload.focus or "note",
        disclaimer=DISCLAIMER,
    )


@router.post("/senior-review", response_model=SeniorReviewResponse)
def post_senior_review(
    payload: SeniorReviewRequest,
    _principal: AuthPrincipal = Depends(require_any_role(*ROLES_HITL)),
) -> SeniorReviewResponse:
    """Senior clinician AI review assist — prioritizes what to check; never adjudicates coverage."""
    result = senior_review_assist(
        patient_id=payload.patient_id,
        case_id=payload.case_id,
        procedure=payload.procedure,
        criteria=[item.model_dump() for item in payload.criteria],
        missing_evidence=list(payload.missing_evidence or []),
        contradictions=list(payload.contradictions or []),
        critic_notes=list(payload.critic_notes or []),
        report_summary=payload.report_summary or "",
    )
    return SeniorReviewResponse(
        briefing=result["briefing"],
        focus_items=[
            SeniorReviewFocusOut.model_validate(item) for item in result["focus_items"]
        ],
        suggested_clinician_note=result["suggested_clinician_note"],
        recommended_desk_action=result["recommended_desk_action"],
        recommended_desk_action_label=result["recommended_desk_action_label"],
        source=result["source"],
        disclaimer=DISCLAIMER,
    )
