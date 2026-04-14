"""Formatting helpers for chat flight responses."""

from __future__ import annotations

import re


def _extract_booking_url(choice: dict) -> str | None:
    """Normalize booking URL fields from different flight result shapes."""
    return (
        choice.get("bookingUrl")
        or choice.get("booking_url")
        or choice.get("booking_token")
    )


def _segment_attr(segment, key: str):
    if isinstance(segment, dict):
        return segment.get(key)
    return getattr(segment, key, None)


def _airport_code(airport) -> str | None:
    if isinstance(airport, dict):
        return airport.get("code") or airport.get("airport")
    return getattr(airport, "code", None) or getattr(airport, "airport", None)


def _format_datetime(value) -> str:
    if isinstance(value, dict):
        date_value = value.get("date", ())
        time_value = value.get("time", ())
    else:
        date_value = getattr(value, "date", None) or ()
        time_value = getattr(value, "time", None) or ()

    if len(date_value) != 3 or len(time_value) == 0:
        return "Unknown time"

    year, month, day = date_value
    hour = time_value[0]
    minute = time_value[1] if len(time_value) > 1 else 0

    if None in (year, month, day, hour, minute):
        return "Unknown time"

    return f"{int(year):04d}-{int(month):02d}-{int(day):02d} {int(hour):02d}:{int(minute):02d}"


def _format_duration(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _build_stops_label(stop_count: int, stop_airports: list[str]) -> str:
    if stop_count == 0:
        return "Direct"

    base = f"{stop_count} stop" + ("s" if stop_count > 1 else "")
    if stop_airports:
        return f"{base} ({', '.join(stop_airports)})"
    return base


def _extract_stop_details_from_segments(segments: list) -> tuple[int, list[str], str]:
    stop_count = max(len(segments) - 1, 0)
    stop_airports: list[str] = []

    for segment in segments[:-1]:
        stop_code = _airport_code(_segment_attr(segment, "to_airport"))
        if stop_code:
            stop_airports.append(stop_code)

    return stop_count, stop_airports, _build_stops_label(stop_count, stop_airports)


def _parse_stops_label(stops: str | None) -> tuple[int, list[str], str]:
    normalized = (stops or "").strip()
    if not normalized or re.search(r"^direct$", normalized, re.IGNORECASE):
        return 0, [], "Direct"

    match = re.match(r"^(\d+)\s*stop", normalized, re.IGNORECASE)
    stop_count = int(match.group(1)) if match else 1

    airports_match = re.search(r"\(([^)]+)\)", normalized)
    stop_airports = []
    if airports_match:
        stop_airports = [part.strip() for part in airports_match.group(1).split(",") if part.strip()]

    return stop_count, stop_airports, _build_stops_label(stop_count, stop_airports)


def _process_flight_segments(segments: list, airlines_list: list, duration: int) -> dict | None:
    """Process a list of flight segments into a single FlightLeg dictionary."""
    if not segments:
        return None

    first_leg = segments[0]
    last_leg = segments[-1]
    stop_count, stop_airports, stops = _extract_stop_details_from_segments(segments)

    departure_airport = _airport_code(_segment_attr(first_leg, "from_airport")) or "UNK"
    arrival_airport = _airport_code(_segment_attr(last_leg, "to_airport")) or "UNK"
    total_duration = int(duration or 0)

    airline_code = _segment_attr(first_leg, "flight_number_airline_code")
    if not airline_code:
        airline_code = (airlines_list or ["NA"])[0]

    departure_time = _format_datetime(_segment_attr(first_leg, "departure"))
    arrival_time = _format_datetime(_segment_attr(last_leg, "arrival"))

    return {
        "airlineCode": airline_code,
        "departure": f"{departure_airport} {departure_time}",
        "arrival": f"{arrival_airport} {arrival_time}",
        "duration": _format_duration(total_duration),
        "duration_minutes": total_duration,
        "stops": stops,
        "stopCount": stop_count,
        "stopAirports": stop_airports,
    }


def _normalize_demo_leg(leg: dict) -> dict:
    stop_count = leg.get("stopCount")
    stop_airports = leg.get("stopAirports")

    if stop_count is not None or stop_airports is not None:
        normalized_stop_count = int(stop_count or 0)
        normalized_stop_airports = [str(code).strip() for code in (stop_airports or []) if str(code).strip()]
        normalized_stops = _build_stops_label(normalized_stop_count, normalized_stop_airports)
    else:
        normalized_stop_count, normalized_stop_airports, normalized_stops = _parse_stops_label(leg.get("stops"))

    return {
        **leg,
        "stops": normalized_stops,
        "stopCount": normalized_stop_count,
        "stopAirports": normalized_stop_airports,
    }


def format_graph_flight(choice: dict, index: int) -> dict:
    """Convert a graph flight choice into the API response shape."""
    legs = []

    outbound_flights = choice.get("flights") or []
    if not outbound_flights:
        raise ValueError("Flight choice is missing outbound flight segments.")
    outbound_leg = _process_flight_segments(
        outbound_flights,
        choice.get("airlines"),
        choice.get("duration"),
    )
    if outbound_leg:
        legs.append(outbound_leg)

    inbound_flights = choice.get("flights_2") or []
    if inbound_flights:
        inbound_leg = _process_flight_segments(
            inbound_flights,
            choice.get("airlines_2"),
            choice.get("duration_2"),
        )
        if inbound_leg:
            legs.append(inbound_leg)

    trip_type = choice.get("trip", "one_way")
    if len(legs) == 2 and trip_type == "one_way":
        trip_type = "round_trip"
    elif len(legs) > 2:
        trip_type = "multi_city"

    return {
        "id": f"result-{index}",
        "price": float(choice.get("price") or 0.0),
        "tripType": trip_type,
        "legs": legs,
        "bookingUrl": _extract_booking_url(choice),
    }


def format_demo_flight(flight: dict) -> dict:
    """Normalize a demo flight into the API response shape."""
    legs = [_normalize_demo_leg(leg) for leg in flight.get("legs", [])]
    trip_type = flight.get("tripType")
    if not trip_type:
        trip_type = "round_trip" if len(legs) == 2 else ("multi_city" if len(legs) > 2 else "one_way")

    return {
        "id": flight["id"],
        "price": flight["price"],
        "tripType": trip_type,
        "legs": legs,
        "bookingUrl": flight.get("bookingUrl"),
    }
