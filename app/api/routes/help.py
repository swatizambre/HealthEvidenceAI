"""In-product help chat for doctors and coordinators (workflow + chart guidance)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.api import HelpChatRequest, HelpChatResponse, HelpTopicsResponse
from app.services.help_desk import answer_help, list_help_topics

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/topics", response_model=HelpTopicsResponse)
def help_topics() -> HelpTopicsResponse:
    return HelpTopicsResponse(topics=list_help_topics())


@router.post("/chat", response_model=HelpChatResponse)
def help_chat(
    payload: HelpChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> HelpChatResponse:
    return answer_help(payload, session=db, settings=request.app.state.settings)
