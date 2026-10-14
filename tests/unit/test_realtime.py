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


def _collect_for_org(org_id: str | None, events: list[dict[str, str | None]]) -> list[str]:
    """Open a stream for ``org_id``, publish ``events``, then return delivered frames."""
    hub = get_hub()
    loop = asyncio.new_event_loop()
    try:
        hub.bind_loop(loop)

        async def _run() -> list[str]:
            frames: list[str] = []
            agen = event_stream(org_id=org_id, heartbeat_seconds=0.1)
            await agen.__anext__()  # connected hello
            for item in events:
                publish_desk_event(
                    "case_assign",
                    org_id=item.get("org_id"),
                    case_id=item.get("case_id"),
                )
            await asyncio.sleep(0.05)
            for _ in range(len(events) + 1):
                frame = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
                if frame.startswith(":"):
                    break  # keepalive — queue drained
                frames.append(frame)
            await agen.aclose()
            return frames

        return loop.run_until_complete(_run())
    finally:
        loop.close()


def test_org_bound_stream_drops_unscoped_and_foreign_events() -> None:
    frames = _collect_for_org(
        "org-a",
        [
            {"org_id": None, "case_id": "PA-UNSCOPED"},
            {"org_id": "org-b", "case_id": "PA-FOREIGN"},
            {"org_id": "org-a", "case_id": "PA-MINE"},
        ],
    )
    joined = "".join(frames)
    assert "PA-MINE" in joined
    assert "PA-UNSCOPED" not in joined
    assert "PA-FOREIGN" not in joined


def test_unbound_stream_sees_all_events() -> None:
    frames = _collect_for_org(
        None,
        [
            {"org_id": None, "case_id": "PA-UNSCOPED"},
            {"org_id": "org-b", "case_id": "PA-FOREIGN"},
        ],
    )
    joined = "".join(frames)
    assert "PA-UNSCOPED" in joined
    assert "PA-FOREIGN" in joined
