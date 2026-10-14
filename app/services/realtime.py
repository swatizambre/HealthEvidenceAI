"""Real-time event bus for desk SSE.



In-process hub always works (single replica). When REDIS_URL is set and the

optional ``redis`` package is installed, publishes fan out via pub/sub so every

API replica's SSE clients see the same desk mutations.

"""



from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any
from uuid import uuid4

logger = logging.getLogger("healthevidence.realtime")



_CHANNEL = "healthevidence:desk"





@dataclass(frozen=True)

class DeskEvent:

    event_id: str

    type: str

    ts: float

    org_id: str | None = None

    case_id: str | None = None

    patient_id: str | None = None

    actor: str | None = None

    detail: dict[str, Any] = field(default_factory=dict)



    def to_sse(self) -> str:

        payload = asdict(self)

        return f"id: {self.event_id}\nevent: {self.type}\ndata: {json.dumps(payload)}\n\n"



    def to_json(self) -> str:

        return json.dumps(asdict(self))



    @classmethod

    def from_json(cls, raw: str) -> DeskEvent | None:

        try:

            data = json.loads(raw)

        except json.JSONDecodeError:

            return None

        if not isinstance(data, dict) or not data.get("event_id") or not data.get("type"):

            return None

        return cls(

            event_id=str(data["event_id"]),

            type=str(data["type"]),

            ts=float(data.get("ts") or time.time()),

            org_id=data.get("org_id"),

            case_id=data.get("case_id"),

            patient_id=data.get("patient_id"),

            actor=data.get("actor"),

            detail=dict(data.get("detail") or {}),

        )





class RealtimeHub:

    def __init__(self) -> None:

        self._lock = Lock()

        self._subscribers: list[asyncio.Queue[DeskEvent | None]] = []

        self._loop: asyncio.AbstractEventLoop | None = None

        self._local_publish_ids: set[str] = set()



    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:

        self._loop = loop



    def subscribe(self) -> asyncio.Queue[DeskEvent | None]:

        queue: asyncio.Queue[DeskEvent | None] = asyncio.Queue(maxsize=64)

        with self._lock:

            self._subscribers.append(queue)

        return queue



    def unsubscribe(self, queue: asyncio.Queue[DeskEvent | None]) -> None:

        with self._lock:

            if queue in self._subscribers:

                self._subscribers.remove(queue)



    def publish(self, event: DeskEvent, *, from_redis: bool = False) -> None:

        if not from_redis:

            with self._lock:

                self._local_publish_ids.add(event.event_id)

                if len(self._local_publish_ids) > 500:

                    self._local_publish_ids.clear()

        else:

            with self._lock:

                if event.event_id in self._local_publish_ids:

                    return

        with self._lock:

            targets = list(self._subscribers)

        if not targets:

            return

        loop = self._loop

        for queue in targets:

            try:

                if loop is not None and loop.is_running():

                    loop.call_soon_threadsafe(self._put_nowait, queue, event)

                else:

                    self._put_nowait(queue, event)

            except Exception as exc:  # noqa: BLE001 — never break writers for fan-out

                logger.debug("realtime_publish_failed err=%s", exc)



    @staticmethod

    def _put_nowait(queue: asyncio.Queue[DeskEvent | None], event: DeskEvent) -> None:

        try:

            queue.put_nowait(event)

        except asyncio.QueueFull:

            try:

                queue.get_nowait()

            except asyncio.QueueEmpty:

                pass

            try:

                queue.put_nowait(event)

            except asyncio.QueueFull:

                pass





_HUB = RealtimeHub()

_REDIS_STOP = threading.Event()

_REDIS_THREAD: threading.Thread | None = None





def get_hub() -> RealtimeHub:

    return _HUB





def _redis_client() -> Any:
    from app.core.config import get_settings

    url = (get_settings().redis_url or "").strip()
    if not url:
        return None
    try:
        import redis
    except ImportError:
        logger.warning("REDIS_URL set but redis package not installed; desk stays in-process")
        return None
    return redis.Redis.from_url(url, decode_responses=True)





def _publish_redis(event: DeskEvent) -> None:

    client = _redis_client()

    if client is None:

        return

    try:

        client.publish(_CHANNEL, event.to_json())

    except Exception as exc:  # noqa: BLE001

        logger.debug("realtime_redis_publish_failed err=%s", exc)





def start_redis_subscriber() -> None:

    """Background Redis → local hub bridge (no-op without REDIS_URL / redis pkg)."""

    global _REDIS_THREAD

    client = _redis_client()

    if client is None:

        return

    if _REDIS_THREAD is not None and _REDIS_THREAD.is_alive():

        return

    _REDIS_STOP.clear()



    def _loop() -> None:

        pubsub = client.pubsub(ignore_subscribe_messages=True)

        pubsub.subscribe(_CHANNEL)

        logger.info("realtime_redis_subscribed channel=%s", _CHANNEL)

        while not _REDIS_STOP.is_set():

            try:

                message = pubsub.get_message(timeout=1.0)

            except Exception as exc:  # noqa: BLE001

                logger.debug("realtime_redis_listen_failed err=%s", exc)

                time.sleep(1.0)

                continue

            if not message or message.get("type") != "message":

                continue

            data = message.get("data")

            if not isinstance(data, str):

                continue

            event = DeskEvent.from_json(data)

            if event is not None:

                get_hub().publish(event, from_redis=True)

        try:

            pubsub.close()

        except Exception:

            pass



    _REDIS_THREAD = threading.Thread(target=_loop, name="he-realtime-redis", daemon=True)

    _REDIS_THREAD.start()





def stop_redis_subscriber() -> None:

    _REDIS_STOP.set()





def publish_desk_event(

    event_type: str,

    *,

    org_id: str | None = None,

    case_id: str | None = None,

    patient_id: str | None = None,

    actor: str | None = None,

    **detail: Any,

) -> DeskEvent:

    event = DeskEvent(

        event_id=str(uuid4()),

        type=event_type,

        ts=time.time(),

        org_id=org_id,

        case_id=case_id,

        patient_id=patient_id,

        actor=actor,

        detail=detail,

    )

    get_hub().publish(event)

    _publish_redis(event)

    logger.info(

        "desk_event type=%s case=%s patient=%s",

        event_type,

        case_id or "",

        patient_id or "",

    )

    return event





async def event_stream(

    *,

    org_id: str | None = None,

    heartbeat_seconds: float = 20.0,

) -> AsyncIterator[str]:

    """Yield SSE frames; optional org filter when tenant scope is on."""

    hub = get_hub()

    try:

        hub.bind_loop(asyncio.get_running_loop())

    except RuntimeError:

        pass

    queue = hub.subscribe()

    try:

        hello = DeskEvent(

            event_id=str(uuid4()),

            type="connected",

            ts=time.time(),

            org_id=org_id,

            detail={"channel": "desk"},

        )

        yield hello.to_sse()

        while True:

            try:

                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)

            except TimeoutError:

                yield ": keepalive\n\n"

                continue

            if item is None:

                break

            # Tenant-bound subscribers only see events stamped with their org. Events
            # without an org_id could belong to any tenant, so they are dropped rather
            # than broadcast (fail closed). Unbound streams (org scope off) see all.
            if org_id and item.org_id != org_id:

                continue

            yield item.to_sse()

    finally:

        hub.unsubscribe(queue)


