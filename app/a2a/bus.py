"""In-process A2A bus with audit-friendly history."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Any

from app.a2a.protocol import AGENT_CAPABILITIES, A2AMessage, new_message
from app.core.exceptions import AppError

Handler = Callable[[A2AMessage], A2AMessage | None]


class A2ABus:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self._history: list[A2AMessage] = []
        self._lock = Lock()

    def register(self, agent: str, handler: Handler) -> None:
        self._handlers[agent] = handler

    def capabilities(self, agent: str | None = None) -> dict[str, list[str]]:
        if agent is None:
            return dict(AGENT_CAPABILITIES)
        return {agent: list(AGENT_CAPABILITIES.get(agent, []))}

    def send(self, message: A2AMessage) -> A2AMessage:
        with self._lock:
            self._history.append(message)
        handler = self._handlers.get(message.recipient)
        if handler is None:
            raise AppError(
                "A2A_UNKNOWN_RECIPIENT",
                f"No A2A handler registered for {message.recipient}.",
                404,
            )
        reply = handler(message)
        if reply is None:
            reply = new_message(
                sender=message.recipient,
                recipient=message.sender,
                kind="ack",
                payload={"acked": message.message_id},
                correlation_id=message.correlation_id,
            )
        with self._lock:
            self._history.append(reply)
        return reply

    def history(self, correlation_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._history)
        if correlation_id:
            rows = [m for m in rows if m.correlation_id == correlation_id]
        return [m.to_dict() for m in rows]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


_BUS = A2ABus()


def get_a2a_bus() -> A2ABus:
    return _BUS
