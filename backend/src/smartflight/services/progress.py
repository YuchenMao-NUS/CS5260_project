"""In-memory progress event bus for streaming chat updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from queue import Queue
from threading import Event, Lock
from typing import Any


class ProgressCancelledError(RuntimeError):
    """Raised when a request-scoped progress channel has been cancelled."""


@dataclass
class ProgressSession:
    queue: Queue[dict[str, Any]] = field(default_factory=Queue)
    cancelled: Event = field(default_factory=Event)


_progress_sessions: dict[str, ProgressSession] = {}
_lock = Lock()


def register_progress_queue(session_id: str) -> Queue[dict[str, Any]]:
    session = ProgressSession()
    with _lock:
        _progress_sessions[session_id] = session
    return session.queue


def unregister_progress_queue(session_id: str) -> None:
    with _lock:
        _progress_sessions.pop(session_id, None)


def cancel_progress(session_id: str | None) -> None:
    if not session_id:
        return

    with _lock:
        session = _progress_sessions.get(session_id)

    if session is not None:
        session.cancelled.set()


def is_progress_cancelled(session_id: str | None) -> bool:
    if not session_id:
        return False

    with _lock:
        session = _progress_sessions.get(session_id)

    return bool(session and session.cancelled.is_set())


def raise_if_progress_cancelled(session_id: str | None) -> None:
    if is_progress_cancelled(session_id):
        raise ProgressCancelledError("Progress stream was cancelled.")


def emit_progress(session_id: str | None, stage: str, message: str) -> None:
    if not session_id:
        return

    with _lock:
        session = _progress_sessions.get(session_id)

    if session is None or session.cancelled.is_set():
        return

    session.queue.put(
        {
            "type": "progress",
            "stage": stage,
            "message": message,
        }
    )


def emit_completed(session_id: str | None, data: dict[str, Any]) -> None:
    if not session_id:
        return

    with _lock:
        session = _progress_sessions.get(session_id)

    if session is None or session.cancelled.is_set():
        return

    session.queue.put(
        {
            "type": "completed",
            "data": data,
        }
    )


def emit_error(session_id: str | None, message: str) -> None:
    if not session_id:
        return

    with _lock:
        session = _progress_sessions.get(session_id)

    if session is None or session.cancelled.is_set():
        return

    session.queue.put(
        {
            "type": "error",
            "message": message,
        }
    )
