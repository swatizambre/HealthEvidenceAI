"""A2A HTTP surface for specialized agent messaging."""

from fastapi import APIRouter

from app.a2a.handlers import register_default_handlers
from app.a2a.protocol import new_message
from app.schemas.api import A2ACapabilitiesResponse, A2AMessageRequest, A2AMessageResponse

router = APIRouter(prefix="/a2a", tags=["a2a"])


@router.get("/capabilities", response_model=A2ACapabilitiesResponse)
def list_capabilities() -> A2ACapabilitiesResponse:
    bus = register_default_handlers()
    return A2ACapabilitiesResponse(capabilities=bus.capabilities())


@router.post("/message", response_model=A2AMessageResponse)
def send_message(payload: A2AMessageRequest) -> A2AMessageResponse:
    bus = register_default_handlers()
    message = new_message(
        sender=payload.sender,
        recipient=payload.recipient,
        kind=payload.kind,
        payload=dict(payload.payload),
        correlation_id=payload.correlation_id,
    )
    reply = bus.send(message)
    return A2AMessageResponse(request=message.to_dict(), reply=reply.to_dict())
