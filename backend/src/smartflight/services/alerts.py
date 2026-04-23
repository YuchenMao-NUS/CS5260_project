from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

from smartflight.config import settings

AlertStatus = Literal["active", "completed", "expired", "cancelled", "error"]


@dataclass
class AlertRecord:
    id: str
    session_id: str
    email: str
    flight_query: dict
    flight_preference: dict
    created_at: datetime
    expires_at: datetime
    status: AlertStatus = "active"
    notified_at: datetime | None = None
    last_error: str | None = None
    metadata: dict = field(default_factory=dict)


_alerts: dict[str, AlertRecord] = {}
_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clone_record(record: AlertRecord) -> AlertRecord:
    return AlertRecord(
        id=record.id,
        session_id=record.session_id,
        email=record.email,
        flight_query=dict(record.flight_query or {}),
        flight_preference=dict(record.flight_preference or {}),
        created_at=record.created_at,
        expires_at=record.expires_at,
        status=record.status,
        notified_at=record.notified_at,
        last_error=record.last_error,
        metadata=dict(record.metadata or {}),
    )


def create_alert(
    *,
    session_id: str,
    email: str,
    flight_query: dict,
    flight_preference: dict | None = None,
    metadata: dict | None = None,
) -> AlertRecord:
    created_at = _now()
    expires_at = created_at + timedelta(hours=max(1, settings.ALERT_TTL_HOURS))
    record = AlertRecord(
        id=str(uuid4()),
        session_id=session_id,
        email=email.strip(),
        flight_query=dict(flight_query or {}),
        flight_preference=dict(flight_preference or {}),
        created_at=created_at,
        expires_at=expires_at,
        metadata=dict(metadata or {}),
    )
    with _lock:
        _alerts[record.id] = record
    return record


def get_alert(alert_id: str) -> AlertRecord | None:
    with _lock:
        record = _alerts.get(alert_id)
        if record is None:
            return None
        return _clone_record(record)


def list_alerts(session_id: str | None = None) -> list[AlertRecord]:
    with _lock:
        records = [_clone_record(record) for record in _alerts.values()]

    if session_id is not None:
        records = [record for record in records if record.session_id == session_id]

    records.sort(key=lambda record: record.created_at, reverse=True)
    return records


def list_active_alerts(now: datetime | None = None) -> list[AlertRecord]:
    check_time = now or _now()
    with _lock:
        return [
            _clone_record(record)
            for record in _alerts.values()
            if record.status == "active" and record.expires_at > check_time
        ]


def mark_alert_completed(alert_id: str, *, notified_at: datetime | None = None) -> None:
    with _lock:
        record = _alerts.get(alert_id)
        if record is None:
            return
        record.status = "completed"
        record.notified_at = notified_at or _now()
        record.last_error = None


def mark_alert_expired(alert_id: str) -> None:
    with _lock:
        record = _alerts.get(alert_id)
        if record is None:
            return
        record.status = "expired"


def mark_alert_cancelled(alert_id: str) -> None:
    with _lock:
        record = _alerts.get(alert_id)
        if record is None:
            return
        record.status = "cancelled"


def cancel_active_alerts(session_id: str, email: str | None = None) -> int:
    normalized_email = (email or "").strip().lower()
    cancelled = 0
    with _lock:
        for record in _alerts.values():
            if record.status != "active":
                continue
            if record.session_id != session_id:
                continue
            if normalized_email and record.email.strip().lower() != normalized_email:
                continue
            record.status = "cancelled"
            cancelled += 1
    return cancelled


def mark_alert_error(alert_id: str, error: str) -> None:
    with _lock:
        record = _alerts.get(alert_id)
        if record is None:
            return
        record.status = "error"
        record.last_error = error


def clear_all_alerts() -> None:
    with _lock:
        _alerts.clear()
