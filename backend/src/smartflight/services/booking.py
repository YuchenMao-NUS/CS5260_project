from __future__ import annotations

from threading import Lock
from typing import TypedDict

from fastapi import HTTPException

from smartflight.agent.filter_flights import fetch_booking_url_for_choice

class ResultSetRecord(TypedDict):
    flight_query: dict
    flight_choices: list[dict]
    demo_flights: dict[str, dict]

_result_sets_by_session: dict[str, dict[str, ResultSetRecord]] = {}
_result_sets_lock = Lock()


def store_result_set(
    session_id: str,
    result_set_id: str,
    flight_query: dict,
    flight_choices: list[dict] | None = None,
    demo_flights: list[dict] | None = None,
) -> None:
    with _result_sets_lock:
        session_results = _result_sets_by_session.setdefault(session_id, {})
        session_results[result_set_id] = {
            "flight_query": dict(flight_query or {}),
            "flight_choices": [dict(choice) for choice in (flight_choices or [])],
            "demo_flights": {
                str(flight.get("id")): dict(flight)
                for flight in (demo_flights or [])
                if flight.get("id")
            },
        }


def _get_result_set(session_id: str, result_set_id: str) -> ResultSetRecord | None:
    with _result_sets_lock:
        session_results = _result_sets_by_session.get(session_id, {})
        result_set = session_results.get(result_set_id)
        if result_set is None:
            return None

        return {
            "flight_query": dict(result_set["flight_query"]),
            "flight_choices": [dict(choice) for choice in result_set["flight_choices"]],
            "demo_flights": {
                flight_id: dict(flight)
                for flight_id, flight in result_set["demo_flights"].items()
            },
        }


def clear_session_results(session_id: str) -> None:
    with _result_sets_lock:
        _result_sets_by_session.pop(session_id, None)


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


def resolve_booking_url(session_id: str, result_set_id: str, flight_id: str) -> str:
    result_set = _get_result_set(session_id, result_set_id)
    if result_set is None:
        raise HTTPException(status_code=404, detail="No saved flight results found for this response.")

    demo_result = result_set["demo_flights"].get(flight_id)
    if demo_result is not None:
        booking_url = demo_result.get("bookingUrl")
        if not booking_url:
            raise HTTPException(status_code=404, detail="Booking link unavailable for this demo flight.")
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
        return saved_booking_url

    booking_url = fetch_booking_url_for_choice(choice, flight_query)
    if not booking_url:
        raise HTTPException(status_code=502, detail="Unable to fetch a booking link for this flight.")

    return booking_url
