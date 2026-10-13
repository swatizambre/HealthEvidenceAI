"""LangGraph checkpointer — durable when DATABASE_URL is file SQLite or Postgres.

MemorySaver remains for in-memory SQLite tests. Resume always falls back to
ReviewRun JSON when no checkpoint thread exists (multi-replica / restart).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("healthevidence.checkpoints")

_LOCK = Lock()
_CHECKPOINTER: BaseCheckpointSaver | None = None
_RESOURCES: list[Any] = []


def thread_config(run_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": str(run_id)}}


def get_checkpointer() -> BaseCheckpointSaver:
    global _CHECKPOINTER
    with _LOCK:
        if _CHECKPOINTER is None:
            _CHECKPOINTER = _build_checkpointer()
        return _CHECKPOINTER


def setup_checkpointer(database_url: str | None = None) -> BaseCheckpointSaver:
    """Create (or reuse) the process checkpointer and run setup() when needed."""
    global _CHECKPOINTER
    with _LOCK:
        close_checkpointer_unlocked()
        _CHECKPOINTER = _build_checkpointer(database_url)
        setup = getattr(_CHECKPOINTER, "setup", None)
        if callable(setup):
            setup()
        return _CHECKPOINTER


def reset_checkpointer() -> None:
    """Test helper — drop interrupt threads / reopen memory saver."""
    global _CHECKPOINTER
    with _LOCK:
        close_checkpointer_unlocked()
        _CHECKPOINTER = MemorySaver()


def close_checkpointer() -> None:
    with _LOCK:
        close_checkpointer_unlocked()


def close_checkpointer_unlocked() -> None:
    global _CHECKPOINTER
    for resource in reversed(_RESOURCES):
        try:
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        except Exception:  # noqa: BLE001 — shutdown best-effort
            logger.debug("checkpointer_resource_close_failed", exc_info=True)
    _RESOURCES.clear()
    _CHECKPOINTER = None


def _build_checkpointer(database_url: str | None = None) -> BaseCheckpointSaver:
    from app.core.config import get_settings

    url = (database_url or get_settings().database_url or "").strip()
    lower = url.lower()

    if lower.startswith("postgresql") or lower.startswith("postgres"):
        try:
            return _postgres_saver(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "postgres_checkpointer_unavailable fallback=memory err=%s",
                str(exc)[:160],
            )
            return MemorySaver()

    if lower.startswith("sqlite"):
        # In-memory / empty URL used by unit tests — keep process MemorySaver.
        if (
            lower in {"sqlite://", "sqlite:///:memory:"}
            or lower.endswith(":memory:")
            or lower == "sqlite://"
        ):
            return MemorySaver()
        path = _sqlite_file_path(url)
        if path is None:
            return MemorySaver()
        try:
            return _sqlite_saver(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sqlite_checkpointer_unavailable fallback=memory err=%s",
                str(exc)[:160],
            )
            return MemorySaver()

    return MemorySaver()


def _sqlite_file_path(database_url: str) -> Path | None:
    raw = database_url.removeprefix("sqlite:///")
    if not raw or raw == ":memory:":
        return None
    db_path = Path(raw)
    # Store LangGraph checkpoints beside the app DB (separate file).
    ckpt = db_path.parent / f"{db_path.stem}.langgraph.sqlite"
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    return ckpt


def _sqlite_saver(path: Path) -> BaseCheckpointSaver:
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(str(path), check_same_thread=False)
    _RESOURCES.append(conn)
    saver = SqliteSaver(conn)
    return saver


def _postgres_saver(database_url: str) -> BaseCheckpointSaver:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # SQLAlchemy urls may use postgresql+psycopg:// — normalize for psycopg.
    conninfo = (
        database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgres+psycopg://", "postgresql://", 1)
    )
    pool = ConnectionPool(
        conninfo=conninfo,
        max_size=8,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )
    _RESOURCES.append(pool)
    return PostgresSaver(pool)  # type: ignore[arg-type]
