from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
from time import perf_counter

from smartflight.agent.state import AgentState, FlightInformation, FlightPreference, FlightQuery
from smartflight.services.flights_mcp import FlightsMcpError, resolve_booking_urls
from smartflight.logging_config import copy_request_context
from smartflight.services.progress import emit_progress, is_progress_cancelled

logger = logging.getLogger(__name__)

DEFAULT_MAX_BOOKING_URL_FETCH_CONCURRENCY = 5
BOOKING_URL_FETCH_TIMEOUT_MS = int(os.getenv("SMARTFLIGHT_BOOKING_URL_FETCH_TIMEOUT_MS", "45000"))
BOOKING_URL_FETCH_MAX_ATTEMPTS = 2
DEFAULT_LANGUAGE = "en-US"
DEFAULT_CURRENCY = "SGD"


def _segment_attr(segment, key: str):
    if isinstance(segment, dict):
        return segment.get(key)
    return getattr(segment, key, None)


def _airport_code(airport) -> str | None:
    if isinstance(airport, dict):
        return airport.get("code") or airport.get("airport")
    return getattr(airport, "code", None) or getattr(airport, "airport", None)


def _date_value(value) -> tuple[int, int, int] | None:
    if isinstance(value, dict):
        date = value.get("date")
    else:
        date = getattr(value, "date", None)
    if isinstance(date, list):
        date = tuple(date)
    if isinstance(date, tuple) and len(date) == 3:
        return (int(date[0]), int(date[1]), int(date[2]))
    return None


def _time_value(value) -> tuple[int, int] | None:
    if isinstance(value, dict):
        time = value.get("time")
    else:
        time = getattr(value, "time", None)
    if isinstance(time, list):
        time = tuple(time)
    if isinstance(time, tuple) and len(time) >= 2:
        return (int(time[0]), int(time[1]))
    return None


def _segment_duration(segment) -> int:
    duration = _segment_attr(segment, "duration")
    return int(duration or 0)


def _segment_airline_code(segment) -> str | None:
    if isinstance(segment, dict):
        return segment.get("flight_number_airline_code")
    return getattr(segment, "flight_number_airline_code", None)


def _segment_flight_number(segment) -> str | None:
    if isinstance(segment, dict):
        return segment.get("flight_number_numeric") or segment.get("flight_number")
    return getattr(segment, "flight_number_numeric", None) or getattr(segment, "flight_number", None)


def _segment_departure(segment):
    return _segment_attr(segment, "departure")


def _segment_arrival(segment):
    return _segment_attr(segment, "arrival")


def _build_booking_itinerary(choice: FlightInformation) -> dict | None:
    if choice["trip"] == "round_trip":
        itinerary = choice.get("selected_itinerary")
        return dict(itinerary) if isinstance(itinerary, dict) else itinerary

    selected_leg = choice.get("selected_leg")
    if not selected_leg:
        return None
    return {"legs": [selected_leg]}


def _build_booking_legs(choice: FlightInformation) -> list[dict[str, str]]:
    legs = [
        {
            "date": choice["departure_date"],
            "origin_airport": choice["from_airport"],
            "destination_airport": choice["to_airport"],
        }
    ]
    if choice["trip"] == "round_trip" and choice.get("return_date"):
        legs.append(
            {
                "date": choice["return_date"],
                "origin_airport": choice["to_airport"],
                "destination_airport": choice["from_airport"],
            }
        )
    return legs


def _to_mcp_trip_type(trip: str) -> str:
    return "round-trip" if trip == "round_trip" else "one-way"


def _to_mcp_passengers(passengers: int) -> dict[str, int]:
    return {
        "adults": max(1, int(passengers)),
        "children": 0,
        "infants_in_seat": 0,
        "infants_on_lap": 0,
    }


def _fetch_booking_url_for_choice(
    choice: FlightInformation,
    flight_query: FlightQuery,
) -> str | None:
    itinerary = _build_booking_itinerary(choice)
    if not itinerary:
        return None

    booking_urls: list[str] = []
    for attempt in range(1, BOOKING_URL_FETCH_MAX_ATTEMPTS + 1):
        try:
            booking_urls = resolve_booking_urls(
                itinerary=itinerary,
                legs=_build_booking_legs(choice),
                trip_type=_to_mcp_trip_type(choice["trip"]),
                passengers=_to_mcp_passengers(flight_query["passengers"]),
                seat=flight_query["seat_classes"],
                language=DEFAULT_LANGUAGE,
                currency=DEFAULT_CURRENCY,
                timeout_seconds=max(1, BOOKING_URL_FETCH_TIMEOUT_MS // 1000),
            )
            break
        except FlightsMcpError as exc:
            logger.warning(
                "Booking URL fetch attempt failed",
                extra={
                    "from_airport": choice["from_airport"],
                    "to_airport": choice["to_airport"],
                    "trip": choice["trip"],
                    "retry_attempt": attempt,
                    "operation": "resolve_booking_urls",
                    "error_code": exc.code,
                    "retryable": exc.retryable,
                    "error_message": str(exc),
                },
            )
            if attempt == BOOKING_URL_FETCH_MAX_ATTEMPTS:
                return None
    if not booking_urls:
        logger.warning(
            "Booking URL fetch returned no URLs",
            extra={
                "from_airport": choice["from_airport"],
                "to_airport": choice["to_airport"],
                "trip": choice["trip"],
                "operation": "resolve_booking_urls",
            },
        )
        return None
    return booking_urls[0]


def _get_total_price(choice: FlightInformation) -> float:
    if choice["trip"] == "one_way":
        return float(choice["price"])
    return float(choice["price"]) + float(choice["price_2"] or 0.0)


def _get_total_duration(choice: FlightInformation) -> int:
    if choice["trip"] == "one_way":
        return int(choice["duration"])
    return int(choice["duration"]) + int(choice["duration_2"] or 0)


def _is_direct_effective(choice: FlightInformation) -> bool:
    if choice["trip"] == "one_way":
        return bool(choice["is_direct"])
    return bool(choice["is_direct"]) and bool(choice["is_direct_2"])


def _leg_stop_count(segments) -> int:
    if not segments:
        return 0
    return max(0, len(segments) - 1)


def _effective_stop_bounds(choice: FlightInformation) -> tuple[int, int]:
    outbound_stops = _leg_stop_count(choice.get("flights") or [])
    if choice["trip"] == "one_way":
        return outbound_stops, outbound_stops
    inbound_stops = _leg_stop_count(choice.get("flights_2") or [])
    return min(outbound_stops, inbound_stops), max(outbound_stops, inbound_stops)


def _all_airlines(choice: FlightInformation) -> list[str]:
    return list(choice.get("airlines") or []) + list(choice.get("airlines_2") or [])


def _matches_preferences(choice: FlightInformation, pref: FlightPreference) -> bool:
    total_price = _get_total_price(choice)
    total_duration = _get_total_duration(choice)
    effective_min_stops, effective_max_stops = _effective_stop_bounds(choice)

    if pref.get("direct_only") is True and not _is_direct_effective(choice):
        return False
    if pref.get("max_stops") is not None and effective_max_stops > pref["max_stops"]:
        return False
    if pref.get("min_stops") is not None and effective_min_stops < pref["min_stops"]:
        return False
    if pref.get("max_price") is not None and total_price > pref["max_price"]:
        return False
    if pref.get("min_price") is not None and total_price < pref["min_price"]:
        return False
    if pref.get("max_duration") is not None and total_duration > pref["max_duration"]:
        return False
    if pref.get("min_duration") is not None and total_duration < pref["min_duration"]:
        return False
    return True


def _compute_rank_score(
    choice: FlightInformation,
    pref: FlightPreference,
    price_min: float,
    price_max: float,
    duration_min: int,
    duration_max: int,
) -> float:
    total_price = _get_total_price(choice)
    total_duration = _get_total_duration(choice)
    is_direct = _is_direct_effective(choice)

    preferred_airlines = pref.get("preferred_airlines") or []
    airline_match = 0
    if preferred_airlines:
        choice_airlines = set(_all_airlines(choice))
        if any(airline in choice_airlines for airline in preferred_airlines):
            airline_match = 1

    price_norm = 0.0 if price_max == price_min else (total_price - price_min) / (price_max - price_min)
    duration_norm = (
        0.0 if duration_max == duration_min else (total_duration - duration_min) / (duration_max - duration_min)
    )
    direct_penalty = 0.0 if is_direct else 0.15
    airline_penalty = 0.0 if airline_match else (0.08 if preferred_airlines else 0.0)
    return 0.55 * price_norm + 0.30 * duration_norm + direct_penalty + airline_penalty


def _attach_booking_url(
    choice: FlightInformation,
    flight_query: FlightQuery,
    progress_id: str | None = None,
    progress_label: str | None = None,
) -> FlightInformation:
    if is_progress_cancelled(progress_id):
        return choice
    if choice.get("booking_url"):
        return choice

    if progress_id and progress_label:
        emit_progress(
            progress_id,
            "preparing_results",
            f"Fetching booking link for {progress_label}...",
        )

    booking_url = _fetch_booking_url_for_choice(choice, flight_query)
    return {**choice, "booking_url": booking_url}


def fetch_booking_url_for_choice(choice: FlightInformation, flight_query: FlightQuery) -> str | None:
    return _attach_booking_url(choice, flight_query).get("booking_url")


def _bounded_concurrency(task_count: int, max_concurrency: int) -> int:
    return max(1, min(task_count, max_concurrency))


def _attach_booking_urls_in_parallel(
    choices: list[FlightInformation],
    flight_query: FlightQuery,
    *,
    max_concurrency: int = DEFAULT_MAX_BOOKING_URL_FETCH_CONCURRENCY,
    progress_id: str | None = None,
) -> list[FlightInformation]:
    if not choices:
        return choices

    ordered_choices: list[FlightInformation | None] = [None] * len(choices)
    worker_count = _bounded_concurrency(len(choices), max_concurrency)
    completed_count = 0

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {}
        for idx, choice in enumerate(choices):
            task_context = copy_request_context()
            future = executor.submit(
                task_context.run,
                _attach_booking_url,
                choice,
                flight_query,
                progress_id,
                f"{choice['from_airport']} -> {choice['to_airport']}",
            )
            future_to_index[future] = idx

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                ordered_choices[idx] = future.result()
                if progress_id:
                    completed_count += 1
                    emit_progress(
                        progress_id,
                        "preparing_results",
                        f"Finished booking link check for {choices[idx]['from_airport']} -> {choices[idx]['to_airport']} ({completed_count}/{len(choices)})...",
                    )
            except Exception:
                logger.warning("Booking URL attachment failed", exc_info=True)
                ordered_choices[idx] = choices[idx]

    return [choice for choice in ordered_choices if choice is not None]


def _keep_best_option_per_destination(choices: list[FlightInformation]) -> list[FlightInformation]:
    best_by_destination: dict[str, FlightInformation] = {}
    for choice in choices:
        best_by_destination.setdefault(choice["to_airport"], choice)
    return list(best_by_destination.values())


def _log_choice_segments(prefix: str, segments: list) -> None:
    for idx, segment in enumerate(segments, 1):
        departure = _segment_departure(segment)
        arrival = _segment_arrival(segment)
        logger.debug(
            "    Leg %d:\n"
            "      %s -> %s\n"
            "      depart: %s %s\n"
            "      arrive: %s %s\n"
            "      duration: %s min\n"
            "      flight_no: %s",
            idx,
            _airport_code(_segment_attr(segment, "from_airport")),
            _airport_code(_segment_attr(segment, "to_airport")),
            _date_value(departure),
            _time_value(departure),
            _date_value(arrival),
            _time_value(arrival),
            _segment_duration(segment),
            _segment_flight_number(segment),
        )


def filter_flights_node(state: AgentState) -> AgentState:
    flight_choices = state.get("flight_choices")
    flight_preference = state.get("flight_preference") or {}
    flight_query = state.get("flight_query") or {}
    progress_id = state.get("progress_id")
    is_multi_destination = flight_query.get("is_multi_destination", False)

    if not flight_choices:
        logger.info(
            "No flight choices to filter",
            extra={"choices_count": 0, "filtered_count": 0},
        )
        return {
            "flight_choices": [],
            "error_message": None,
        }

    try:
        emit_progress(progress_id, "ranking_results", "Ranking and filtering flight results...")
        logger.info(
            "Filtering flight choices started",
            extra={
                "choices_count": len(flight_choices),
                "trip": flight_query.get("trip"),
            },
        )

        filtered_choices = [
            choice for choice in flight_choices if _matches_preferences(choice, flight_preference)
        ]
        if not filtered_choices:
            logger.warning(
                "No matching flights after preference filters",
                extra={
                    "choices_count": len(flight_choices),
                    "filtered_count": 0,
                    "trip": flight_query.get("trip"),
                },
            )
            return {"flight_choices": [], "error_message": None}

        prices = [_get_total_price(choice) for choice in filtered_choices]
        durations = [_get_total_duration(choice) for choice in filtered_choices]
        price_min = min(prices) if prices else 0.0
        price_max = max(prices) if prices else 0.0
        duration_min = min(durations) if durations else 0
        duration_max = max(durations) if durations else 0

        def sort_key(choice: FlightInformation):
            score = _compute_rank_score(
                choice=choice,
                pref=flight_preference,
                price_min=price_min,
                price_max=price_max,
                duration_min=duration_min,
                duration_max=duration_max,
            )
            return (
                score,
                _get_total_price(choice),
                _get_total_duration(choice),
                0 if _is_direct_effective(choice) else 1,
            )

        sorted_choices = sorted(filtered_choices, key=sort_key)
        if is_multi_destination:
            sorted_choices = _keep_best_option_per_destination(sorted_choices)

        result = {
            **state,
            "flight_choices": sorted_choices,
            "error_message": None,
        }

        logger.debug("=== flight_query ===")
        for key, value in (result.get("flight_query") or {}).items():
            logger.debug("  %s: %s", key, value)

        logger.debug("\n=== flight_preference ===")
        for key, value in (result.get("flight_preference") or {}).items():
            logger.debug("  %s: %s", key, value)

        logger.debug("\n=== flight_choices ===")
        for i, choice in enumerate(result.get("flight_choices") or [], 1):
            logger.debug(
                "\n--- Option %d ---\n"
                "  trip: %s\n"
                "  route: %s -> %s\n"
                "  departure_date: %s",
                i,
                choice["trip"],
                choice["from_airport"],
                choice["to_airport"],
                choice["departure_date"],
            )
            if choice.get("return_date"):
                logger.debug("  return_date: %s", choice["return_date"])

            logger.debug(
                "\n  [Outbound]\n"
                "    airlines: %s\n"
                "    price: %s\n"
                "    duration: %s min\n"
                "    direct: %s",
                choice["airlines"],
                choice["price"],
                choice["duration"],
                choice["is_direct"],
            )
            _log_choice_segments("Outbound", choice.get("flights") or [])

            if choice["trip"] == "round_trip":
                logger.debug(
                    "\n  [Inbound]\n"
                    "    airlines: %s\n"
                    "    price: %s\n"
                    "    duration: %s min\n"
                    "    direct: %s",
                    choice.get("airlines_2"),
                    choice.get("price_2"),
                    choice.get("duration_2"),
                    choice.get("is_direct_2"),
                )
                _log_choice_segments("Inbound", choice.get("flights_2") or [])

        logger.info(
            "Filtering flight choices completed",
            extra={
                "choices_count": len(flight_choices),
                "filtered_count": len(sorted_choices),
                "trip": flight_query.get("trip"),
            },
        )
        return result
    except Exception as exc:
        return {
            "error_message": f"Flight filtering failed: {exc}",
        }
