"""Server-Sent Events stream for real-time desk updates."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_principal, require_care_team
from app.auth.oidc import AuthPrincipal
from app.services.org_scope import care_team_org_filter_id
from app.services.realtime import event_stream, get_hub

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def desk_event_stream(
    request: Request,
    principal: AuthPrincipal = Depends(require_care_team()),
    access_token: str | None = Query(
        default=None,
        alias="access_token",
        description="Bearer alternative for EventSource (no custom headers).",
    ),
) -> StreamingResponse:
    """Push desk mutations (prepare, assign, review, visit ingest) to open browsers."""
    del access_token  # validated by AuthMiddleware when present as query
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
