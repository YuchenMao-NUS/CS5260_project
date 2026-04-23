from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from threading import Lock
from typing import TypedDict

from fastapi import HTTPException

from smartflight.agent.filter_flights import fetch_booking_url_for_choice
from smartflight.config import settings

logger = logging.getLogger(__name__)


class ResultSetRecord(TypedDict):
    flight_query: dict
    flight_choices: list[dict]
    demo_flights: dict[str, dict]


class LatestIntentRecord(TypedDict):
    flight_query: dict
    flight_preference: dict


_result_sets_by_session: dict[str, dict[str, ResultSetRecord]] = {}
_result_sets_lock = Lock()
_latest_intent_by_session: dict[str, LatestIntentRecord] = {}
_RESULT_SET_STORE_ROOT = settings.PROJECT_ROOT / "backend" / ".cache" / "result_sets"


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _result_set_path(session_id: str, result_set_id: str) -> Path:
    return _RESULT_SET_STORE_ROOT / f"{_stable_key(session_id)}-{_stable_key(result_set_id)}.json"


def _copy_record(record: ResultSetRecord) -> ResultSetRecord:
    return {
        "flight_query": dict(record["flight_query"]),
        "flight_choices": [dict(choice) for choice in record["flight_choices"]],
        "demo_flights": {
            flight_id: dict(flight)
            for flight_id, flight in record["demo_flights"].items()
        },
    }


def _write_result_set(session_id: str, result_set_id: str, record: ResultSetRecord) -> None:
    _RESULT_SET_STORE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _result_set_path(session_id, result_set_id)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _read_result_set(session_id: str, result_set_id: str) -> ResultSetRecord | None:
    path = _result_set_path(session_id, result_set_id)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "Saved result set cache read failed",
            extra={"session_id": session_id, "result_set_id": result_set_id},
            exc_info=True,
        )
        return None

    return {
        "flight_query": dict(payload.get("flight_query") or {}),
        "flight_choices": [dict(choice) for choice in (payload.get("flight_choices") or [])],
        "demo_flights": {
            str(flight_id): dict(flight)
            for flight_id, flight in (payload.get("demo_flights") or {}).items()
        },
    }


def store_result_set(
    session_id: str,
    result_set_id: str,
    flight_query: dict,
    flight_choices: list[dict] | None = None,
    demo_flights: list[dict] | None = None,
) -> None:
    record: ResultSetRecord = {
        "flight_query": dict(flight_query or {}),
        "flight_choices": [dict(choice) for choice in (flight_choices or [])],
        "demo_flights": {
            str(flight.get("id")): dict(flight)
            for flight in (demo_flights or [])
            if flight.get("id")
        },
    }

    with _result_sets_lock:
        session_results = _result_sets_by_session.setdefault(session_id, {})
        session_results[result_set_id] = record

    try:
        _write_result_set(session_id, result_set_id, record)
    except (OSError, TypeError):
        logger.warning(
            "Saved result set cache write failed",
            extra={"session_id": session_id, "result_set_id": result_set_id},
            exc_info=True,
        )


def _get_result_set(session_id: str, result_set_id: str) -> ResultSetRecord | None:
    with _result_sets_lock:
        session_results = _result_sets_by_session.get(session_id, {})
        result_set = session_results.get(result_set_id)
        if result_set is not None:
            return _copy_record(result_set)

    result_set = _read_result_set(session_id, result_set_id)
    if result_set is None:
        return None

    with _result_sets_lock:
        session_results = _result_sets_by_session.setdefault(session_id, {})
        session_results[result_set_id] = result_set

    logger.info(
        "Saved result set cache loaded",
        extra={"session_id": session_id, "result_set_id": result_set_id},
    )
    return _copy_record(result_set)


def clear_session_results(session_id: str) -> None:
    with _result_sets_lock:
        _result_sets_by_session.pop(session_id, None)
        _latest_intent_by_session.pop(session_id, None)

    prefix = f"{_stable_key(session_id)}-"
    if not _RESULT_SET_STORE_ROOT.exists():
        return
    for path in _RESULT_SET_STORE_ROOT.glob(f"{prefix}*.json"):
        path.unlink(missing_ok=True)


def remember_latest_intent(
    session_id: str,
    flight_query: dict,
    flight_preference: dict | None = None,
) -> None:
    if not flight_query:
        return
    with _result_sets_lock:
        _latest_intent_by_session[session_id] = {
            "flight_query": dict(flight_query or {}),
            "flight_preference": dict(flight_preference or {}),
        }


def get_latest_intent(session_id: str) -> LatestIntentRecord | None:
    with _result_sets_lock:
        record = _latest_intent_by_session.get(session_id)
        if record is None:
            return None
        return {
            "flight_query": dict(record["flight_query"]),
            "flight_preference": dict(record["flight_preference"]),
        }


def _choice_for_flight_id(flight_choices: list[dict], flight_id: str) -> dict | None:
    prefix = "result-"
    if not flight_id.startswith(prefix):
        return None

    index_str = flight_id[len(prefix):]
    if not index_str.isdigit():
        return None

    index = int(index_str) - 1
    if index < 0 or index >= len(flight_choices):
        return None

    return flight_choices[index]


def _save_booking_url(
    session_id: str,
    result_set_id: str,
    flight_id: str,
    booking_url: str,
) -> None:
    prefix = "result-"
    if not flight_id.startswith(prefix):
        return

    index_str = flight_id[len(prefix):]
    if not index_str.isdigit():
        return

    index = int(index_str) - 1
    with _result_sets_lock:
        result_set = _result_sets_by_session.get(session_id, {}).get(result_set_id)
        if result_set is None or index < 0 or index >= len(result_set["flight_choices"]):
            return
        result_set["flight_choices"][index]["booking_url"] = booking_url
        record = _copy_record(result_set)

    try:
        _write_result_set(session_id, result_set_id, record)
    except (OSError, TypeError):
        logger.warning(
            "Saved booking URL cache update failed",
            extra={"session_id": session_id, "result_set_id": result_set_id, "flight_id": flight_id},
            exc_info=True,
        )


def resolve_booking_url(session_id: str, result_set_id: str, flight_id: str) -> str:
    result_set = _get_result_set(session_id, result_set_id)
    if result_set is None:
        logger.warning(
            "Saved result set not found",
            extra={
                "session_id": session_id,
                "result_set_id": result_set_id,
                "flight_id": flight_id,
                "status_code": 404,
            },
        )
        raise HTTPException(status_code=404, detail="No saved flight results found for this response.")

    demo_result = result_set["demo_flights"].get(flight_id)
    if demo_result is not None:
        booking_url = demo_result.get("bookingUrl")
        if not booking_url:
            raise HTTPException(status_code=404, detail="Booking link unavailable for this demo flight.")
        logger.info(
            "Saved booking URL reused",
            extra={"session_id": session_id, "result_set_id": result_set_id, "flight_id": flight_id},
        )
        return booking_url

    flight_query = result_set["flight_query"]
    flight_choices = result_set["flight_choices"]

    if not flight_choices or not flight_query:
        raise HTTPException(status_code=404, detail="No saved live flight results found for this response.")

    choice = _choice_for_flight_id(flight_choices, flight_id)
    if choice is None:
        raise HTTPException(status_code=404, detail="Flight not found in this response.")

    saved_booking_url = choice.get("booking_url") or choice.get("bookingUrl")
    if saved_booking_url:
        logger.info(
            "Saved booking URL reused",
            extra={"session_id": session_id, "result_set_id": result_set_id, "flight_id": flight_id},
        )
        return saved_booking_url

    logger.info(
        "Lazy booking URL fetch started",
        extra={"session_id": session_id, "result_set_id": result_set_id, "flight_id": flight_id},
    )
    booking_url = fetch_booking_url_for_choice(choice, flight_query)
    if not booking_url:
        logger.warning(
            "Lazy booking URL fetch failed",
            extra={
                "session_id": session_id,
                "result_set_id": result_set_id,
                "flight_id": flight_id,
                "status_code": 502,
            },
        )
        raise HTTPException(status_code=502, detail="Unable to fetch a booking link for this flight.")

    _save_booking_url(session_id, result_set_id, flight_id, booking_url)
    logger.info(
        "Lazy booking URL fetch completed",
        extra={"session_id": session_id, "result_set_id": result_set_id, "flight_id": flight_id},
    )
    return booking_url
