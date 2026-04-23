"""Google Flights HTML and payload parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from flights_search.models import (
    Airport,
    CarbonData,
    ContinuationHandle,
    FlightOption,
    FlightSegment,
    SearchResults,
)


def parse_search_html(html: str) -> SearchResults:
    """Parse Google Flights HTML into typed search results."""

    payload = _extract_payload_from_html(html)
    return parse_search_payload(payload)


def parse_search_payload(payload: list[Any]) -> SearchResults:
    """Parse a decoded Google Flights payload into typed search results."""

    rows, selection_phase = _get_rows_and_phase(payload)
    parsed_options: list[FlightOption] = []
    for row in rows:
        option = _parse_option(row)
        if option is not None:
            parsed_options.append(option)
    options = tuple(parsed_options)
    return SearchResults(options=options, selection_phase=selection_phase)


def _extract_payload_from_html(html: str) -> list[Any]:
    text = _extract_script_text(html)
    if not text or "data:" not in text:
        raise ValueError("Could not find Google Flights payload data in HTML.")

    data = text.split("data:", 1)[1].rsplit(",", 1)[0]
    payload = json.loads(data)
    if not isinstance(payload, list):
        raise ValueError("Google Flights payload must decode to a list.")
    return payload


def _extract_script_text(html: str) -> str:
    try:
        from selectolax.lexbor import LexborHTMLParser
    except ModuleNotFoundError:
        match = re.search(
            r'<script[^>]*class=["\']ds:1["\'][^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL,
        )
        if match is None:
            raise ValueError("Could not find Google Flights payload script in HTML.")
        return match.group(1)

    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if script is None:
        raise ValueError("Could not find Google Flights payload script in HTML.")
    return script.text()


def _get_rows_and_phase(
    payload: list[Any],
) -> tuple[list[Any], str]:
    initial_rows = _safe_get(payload, 2, 0, default=[])
    if isinstance(initial_rows, list) and initial_rows:
        return initial_rows, "initial"

    follow_up_rows = _safe_get(payload, 3, 0, default=[])
    if isinstance(follow_up_rows, list) and follow_up_rows:
        return follow_up_rows, "follow-up"

    return [], "initial"


def _parse_option(row: Any) -> FlightOption | None:
    if not isinstance(row, list) or len(row) < 2:
        return None

    flight = _safe_get(row, 0)
    price = _safe_get(row, 1, 0, 1)
    continuation_value = _safe_get(row, 1, 1)

    if not isinstance(flight, list) or price is None:
        return None

    kind = _safe_get(flight, 0, default="unknown")
    airlines = _safe_get(flight, 1, default=[])
    raw_segments = _safe_get(flight, 2, default=[])
    extras = _safe_get(flight, 21, default=[])

    if not isinstance(raw_segments, list) or not raw_segments:
        return None

    segments = tuple(
        segment for raw_segment in raw_segments if (segment := _parse_segment(raw_segment))
    )
    if not segments:
        return None

    carbon = _parse_carbon_data(extras)
    continuation = None
    if isinstance(continuation_value, str) and continuation_value:
        continuation = ContinuationHandle(continuation_value)

    return FlightOption(
        kind=kind if isinstance(kind, str) else "unknown",
        price=price if isinstance(price, int) else None,
        airlines=tuple(item for item in airlines if isinstance(item, str)),
        segments=segments,
        carbon=carbon,
        continuation=continuation,
    )


def _parse_segment(raw_segment: Any) -> FlightSegment | None:
    if not isinstance(raw_segment, list):
        return None

    origin_code = _safe_get(raw_segment, 3)
    origin_name = _safe_get(raw_segment, 4)
    destination_name = _safe_get(raw_segment, 5)
    destination_code = _safe_get(raw_segment, 6)
    departure_time = _safe_get(raw_segment, 8)
    arrival_time = _safe_get(raw_segment, 10)
    duration_minutes = _safe_get(raw_segment, 11)
    aircraft_type = _safe_get(raw_segment, 17)
    flight_number = _safe_get(raw_segment, 22)

    if not all(
        isinstance(value, str)
        for value in (origin_code, origin_name, destination_code, destination_name)
    ):
        return None
    if not isinstance(departure_time, list) or not isinstance(arrival_time, list):
        return None
    if not isinstance(duration_minutes, int):
        return None

    marketing_airline_code = None
    marketing_flight_number = None
    if (
        isinstance(flight_number, list)
        and len(flight_number) >= 2
        and isinstance(flight_number[0], str)
        and isinstance(flight_number[1], str)
    ):
        marketing_airline_code = flight_number[0]
        marketing_flight_number = flight_number[1]

    return FlightSegment(
        origin=Airport(code=origin_code, name=origin_name),
        destination=Airport(code=destination_code, name=destination_name),
        departure_time=_format_clock_time(departure_time),
        arrival_time=_format_clock_time(arrival_time),
        duration_minutes=duration_minutes,
        marketing_airline_code=marketing_airline_code,
        flight_number=marketing_flight_number,
        aircraft_type=aircraft_type if isinstance(aircraft_type, str) else None,
    )


def _parse_carbon_data(extras: Any) -> CarbonData | None:
    emitted_grams = _safe_get(extras, 7)
    typical_route_grams = _safe_get(extras, 8)
    if not isinstance(emitted_grams, int) or not isinstance(typical_route_grams, int):
        return None
    return CarbonData(
        typical_route_grams=typical_route_grams,
        emitted_grams=emitted_grams,
    )


def _format_clock_time(value: list[Any]) -> str:
    if not value:
        raise ValueError("Expected Google Flights time value to contain time parts.")

    raw_hour = value[0]
    raw_minute = value[1] if len(value) >= 2 else None

    if raw_hour is None and isinstance(raw_minute, int):
        hour = 0
        minute = raw_minute
    elif isinstance(raw_hour, int):
        hour = raw_hour
        minute = raw_minute if isinstance(raw_minute, int) else 0
    else:
        raise ValueError("Expected Google Flights time value to contain an hour.")

    return f"{hour:02d}:{minute:02d}"


def _safe_get(obj: Any, *indexes: int, default: Any = None) -> Any:
    current = obj
    for index in indexes:
        try:
            current = current[index]
        except (IndexError, KeyError, TypeError):
            return default
    return current
