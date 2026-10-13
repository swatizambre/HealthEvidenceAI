"""Server-Sent Events stream for real-time desk updates."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_principal, require_care_team
from app.auth.oidc import AuthPrincipal
from app.auth.stream_ticket import issue_stream_ticket
from app.schemas.api import StreamTicketResponse
from app.services.org_scope import care_team_org_filter_id
from app.services.realtime import event_stream, get_hub

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/stream-ticket", response_model=StreamTicketResponse)
def create_stream_ticket(
    request: Request,
    principal: AuthPrincipal = Depends(require_care_team()),
) -> StreamTicketResponse:
    """Mint a ~60 s single-use ticket for ``GET /events/stream?ticket=...``.

    EventSource cannot send an Authorization header; the ticket keeps the long-lived
    bearer token out of URLs (proxy/access logs, browser history).
    """
    settings = request.app.state.settings
    if settings.auth_mode.strip().lower() in {"", "none", "off", "disabled"}:
        # Auth off (unit tests): the stream needs no credential, so no ticket is minted.
        return StreamTicketResponse(ticket="", expires_in=0)
    ticket, expires_in = issue_stream_ticket(get_principal(request) or principal, settings)
    return StreamTicketResponse(ticket=ticket, expires_in=expires_in)


@router.get("/stream")
async def desk_event_stream(
    request: Request,
    principal: AuthPrincipal = Depends(require_care_team()),
) -> StreamingResponse:
    """Push desk mutations (prepare, assign, review, visit ingest) to open browsers.

    Authenticate with ``Authorization: Bearer`` or ``?ticket=`` from POST /stream-ticket.
    """
    get_hub().bind_loop(asyncio.get_running_loop())

    org_id: str | None = None
    session = request.app.state.session_factory()
    try:
        org_id = care_team_org_filter_id(session, get_principal(request) or principal)
    finally:
        session.close()

    async def _generate() -> AsyncIterator[Any]:
        async for chunk in event_stream(org_id=org_id):
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
