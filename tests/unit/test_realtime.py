"""Real-time desk event bus."""

from __future__ import annotations

import asyncio

from app.services.realtime import event_stream, get_hub, publish_desk_event
from tests.conftest import make_client


def test_publish_fans_out_to_subscriber() -> None:
    hub = get_hub()
    loop = asyncio.new_event_loop()
    try:
        hub.bind_loop(loop)

        async def _run() -> list[str]:
            chunks: list[str] = []
            agen = event_stream(org_id=None, heartbeat_seconds=0.2)
            chunks.append(await agen.__anext__())
            publish_desk_event(
                "evidence_pack_prepare",
                case_id="PA-000001",
                patient_id="PAT-000001",
            )
            await asyncio.sleep(0.05)
            chunks.append(await asyncio.wait_for(agen.__anext__(), timeout=1.0))
            await agen.aclose()
            return chunks

        frames = loop.run_until_complete(_run())
        assert any("connected" in frame for frame in frames)
        assert any("evidence_pack_prepare" in frame for frame in frames)
    finally:
        loop.close()


def test_stream_requires_auth_when_dev_jwt(monkeypatch) -> None:
    with make_client(monkeypatch, AUTH_MODE="dev-jwt") as client:
        denied = client.get("/api/v1/events/stream")
        assert denied.status_code == 401
