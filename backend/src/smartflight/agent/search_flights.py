from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from time import perf_counter

import logging

from smartflight.agent.state import AgentState, FlightInformation, FlightQuery
from smartflight.logging_config import copy_request_context
from smartflight.services.flights_mcp import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    FlightsMcpError,
    search_flights as mcp_search_flights,
    search_return_flights as mcp_search_return_flights,
)
from smartflight.services.progress import emit_progress, is_progress_cancelled

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUTE_SEARCH_CONCURRENCY = 10
SEARCH_TOOL_TIMEOUT_SECONDS = DEFAULT_TOOL_TIMEOUT_SECONDS
DEFAULT_LANGUAGE = "en-US"
DEFAULT_CURRENCY = "SGD"


def _to_mcp_trip_type(trip: str) -> str:
    trip_map = {
        "one_way": "one-way",
        "round_trip": "round-trip",
    }
    if trip not in trip_map:
        raise ValueError(f"Unsupported trip type: {trip}")
    return trip_map[trip]


def _to_mcp_passengers(passengers: int) -> dict[str, int]:
    return {
        "adults": max(1, int(passengers)),
        "children": 0,
        "infants_in_seat": 0,
        "infants_on_lap": 0,
    }


def _parse_date_tuple(date_str: str) -> tuple[int, int, int]:
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    return (parsed.year, parsed.month, parsed.day)


def _parse_time_tuple(time_str: str | None) -> tuple[int, int]:
    if not time_str:
        return (0, 0)
    hour_str, minute_str = time_str.split(":", 1)
    return (int(hour_str), int(minute_str))


def _adapt_segment(segment: dict) -> dict:
    date_tuple = _parse_date_tuple(segment["date"])
    return {
        "from_airport": {
            "code": segment["origin_airport"],
            "name": segment.get("origin_airport_name"),
        },
        "to_airport": {
            "code": segment["destination_airport"],
            "name": segment.get("destination_airport_name"),
        },
        "departure": {
            "date": date_tuple,
            "time": _parse_time_tuple(segment.get("departure_time")),
        },
        "arrival": {
            "date": date_tuple,
            "time": _parse_time_tuple(segment.get("arrival_time")),
        },
        "duration": int(segment.get("duration_minutes") or 0),
        "plane_type": segment.get("aircraft_type"),
        "flight_number": (
            f"{segment['marketing_airline_code']}{segment['flight_number']}"
            if segment.get("marketing_airline_code") and segment.get("flight_number")
            else segment.get("flight_number")
        ),
        "flight_number_airline_code": segment.get("marketing_airline_code"),
        "flight_number_numeric": segment.get("flight_number"),
    }


def _adapt_option_segments(option: dict) -> list[dict]:
    return [_adapt_segment(segment) for segment in option.get("segments") or []]


def _build_legs(
    *,
    from_airport: str,
    to_airport: str,
    departure_date: str,
    return_date: str | None = None,
) -> list[dict[str, str]]:
    legs = [
        {
            "date": departure_date,
            "origin_airport": from_airport,
            "destination_airport": to_airport,
        }
    ]
    if return_date:
        legs.append(
            {
                "date": return_date,
                "origin_airport": to_airport,
                "destination_airport": from_airport,
            }
        )
    return legs


def _adapt_one_way_option(
    *,
    option: dict,
    from_airport: str,
    to_airport: str,
    departure_date: str,
) -> FlightInformation | None:
    outbound_flights = _adapt_option_segments(option)
    if not outbound_flights:
        return None

    duration = sum(int(segment["duration"]) for segment in outbound_flights)
    return {
        "trip": "one_way",
        "from_airport": from_airport,
        "to_airport": to_airport,
        "departure_date": departure_date,
        "return_date": None,
        "booking_url": None,
        "outbound_selection_handle": option.get("outbound_selection_handle"),
        "selected_leg": option.get("selected_leg"),
        "selected_itinerary": option.get("selected_itinerary"),
        "is_direct": len(outbound_flights) == 1,
        "airlines": list(option.get("airlines") or []),
        "price": float(option.get("price") or 0.0),
        "duration": duration,
        "flights": outbound_flights,
        "is_direct_2": None,
        "airlines_2": None,
        "price_2": None,
        "duration_2": None,
        "flights_2": None,
    }


def _adapt_round_trip_option(
    *,
    outbound_option: dict,
    inbound_option: dict,
    from_airport: str,
    to_airport: str,
    departure_date: str,
    return_date: str,
) -> FlightInformation | None:
    outbound_flights = _adapt_option_segments(outbound_option)
    inbound_flights = _adapt_option_segments(inbound_option)
    if not outbound_flights or not inbound_flights:
        return None

    outbound_duration = sum(int(segment["duration"]) for segment in outbound_flights)
    inbound_duration = sum(int(segment["duration"]) for segment in inbound_flights)
    return {
        "trip": "round_trip",
        "from_airport": from_airport,
        "to_airport": to_airport,
        "departure_date": departure_date,
        "return_date": return_date,
        "booking_url": None,
        "outbound_selection_handle": outbound_option.get("outbound_selection_handle"),
        "selected_leg": outbound_option.get("selected_leg"),
        "selected_itinerary": inbound_option.get("selected_itinerary"),
        "is_direct": len(outbound_flights) == 1,
        "airlines": list(outbound_option.get("airlines") or []),
        "price": float(outbound_option.get("price") or 0.0),
        "duration": outbound_duration,
        "flights": outbound_flights,
        "is_direct_2": len(inbound_flights) == 1,
        "airlines_2": list(inbound_option.get("airlines") or []),
        "price_2": float(inbound_option.get("price") or 0.0),
        "duration_2": inbound_duration,
        "flights_2": inbound_flights,
    }


def _bounded_concurrency(task_count: int, max_concurrency: int) -> int:
    return max(1, min(task_count, max_concurrency))


def _collect_parallel_route_results(route_tasks, *, max_concurrency: int):
    if not route_tasks:
        return []

    ordered_results = [None] * len(route_tasks)
    worker_count = _bounded_concurrency(len(route_tasks), max_concurrency)
    completed_count = 0

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {}
        for idx, task in enumerate(route_tasks):
            task_context = copy_request_context()
            future_to_index[executor.submit(task_context.run, task["fn"])] = idx

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            route_label = route_tasks[idx]["label"]
            try:
                ordered_results[idx] = future.result()
                if route_tasks[idx].get("progress_id"):
                    completed_count += 1
                    emit_progress(
                        route_tasks[idx]["progress_id"],
                        "searching_flights",
                        f"Finished {route_tasks[idx]['display_label']} ({completed_count}/{len(route_tasks)})...",
                    )
            except Exception as exc:
                logger.warning(
                    "Route search failed",
                    extra={"operation": "search_flights", "to_airport": route_tasks[idx].get("to_airport")},
                    exc_info=True,
                )
                ordered_results[idx] = []

    return ordered_results


def _search_one_way_route(
    from_airport: str,
    to_airport: str,
    departure_date: str,
    seat_class: str,
    passengers: int,
    progress_id: str | None = None,
    route_index: int | None = None,
    route_total: int | None = None,
) -> list[FlightInformation]:
    route_label = f"{from_airport} -> {to_airport} on {departure_date}"
    started_at = perf_counter()
    logger.info(
        "Route search started",
        extra={
            "from_airport": from_airport,
            "to_airport": to_airport,
            "departure_date": departure_date,
            "trip": "one_way",
            "operation": "search_flights",
            "provider": "mcp",
        },
    )

    if is_progress_cancelled(progress_id):
        return []

    if progress_id and route_index is not None and route_total is not None:
        emit_progress(
            progress_id,
            "searching_flights",
            f"Checking {from_airport} -> {to_airport} ({route_index}/{route_total})...",
        )

    payload = mcp_search_flights(
        legs=_build_legs(
            from_airport=from_airport,
            to_airport=to_airport,
            departure_date=departure_date,
        ),
        trip_type=_to_mcp_trip_type("one_way"),
        passengers=_to_mcp_passengers(passengers),
        seat=seat_class,
        language=DEFAULT_LANGUAGE,
        currency=DEFAULT_CURRENCY,
        timeout_seconds=SEARCH_TOOL_TIMEOUT_SECONDS,
    )

    flight_choices = [
        adapted
        for option in payload.get("options") or []
        if (adapted := _adapt_one_way_option(
            option=option,
            from_airport=from_airport,
            to_airport=to_airport,
            departure_date=departure_date,
        ))
        is not None
    ]

    logger.info(
        "Route search completed",
        extra={
            "from_airport": from_airport,
            "to_airport": to_airport,
            "departure_date": departure_date,
            "trip": "one_way",
            "results_count": len(flight_choices),
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
            "operation": "search_flights",
            "provider": "mcp",
        },
    )
    return flight_choices


def search_one_way(
    flight_query: FlightQuery,
    *,
    max_concurrency: int = DEFAULT_MAX_ROUTE_SEARCH_CONCURRENCY,
    progress_id: str | None = None,
) -> list[FlightInformation]:
    from_airport = flight_query["from_airport"]
    to_airports = flight_query["to_airports"]
    departure_date = flight_query["departure_date"]
    seat_class = flight_query["seat_classes"]
    passengers = flight_query["passengers"]
    started_at = perf_counter()

    if progress_id:
        emit_progress(
            progress_id,
            "searching_flights",
            f"Searching {len(to_airports)} destination(s) from {from_airport} on {departure_date}...",
        )
        if is_progress_cancelled(progress_id):
            return []

    route_tasks = [
        {
            "label": f"{from_airport} -> {to_airport} on {departure_date}",
            "display_label": f"{from_airport} -> {to_airport}",
            "to_airport": to_airport,
            "progress_id": progress_id,
            "fn": lambda to_airport=to_airport, route_index=idx + 1, route_total=len(to_airports): _search_one_way_route(
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date=departure_date,
                seat_class=seat_class,
                passengers=passengers,
                progress_id=progress_id,
                route_index=route_index,
                route_total=route_total,
            ),
        }
        for idx, to_airport in enumerate(to_airports)
    ]

    route_results = _collect_parallel_route_results(
        route_tasks,
        max_concurrency=max_concurrency,
    )
    flight_choices = [choice for route_result in route_results for choice in route_result]

    logger.info(
        "Flight search completed",
        extra={
            "from_airport": from_airport,
            "departure_date": departure_date,
            "trip": "one_way",
            "results_count": len(flight_choices),
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
        },
    )
    return flight_choices


def _search_round_trip_route(
    from_airport: str,
    to_airport: str,
    departure_date: str,
    return_date: str,
    seat_class: str,
    passengers: int,
    progress_id: str | None = None,
    route_index: int | None = None,
    route_total: int | None = None,
) -> list[FlightInformation]:
    route_label = f"{from_airport} <-> {to_airport} ({departure_date} / {return_date})"
    started_at = perf_counter()
    logger.info(
        "Route search started",
        extra={
            "from_airport": from_airport,
            "to_airport": to_airport,
            "departure_date": departure_date,
            "return_date": return_date,
            "trip": "round_trip",
            "operation": "search_flights",
            "provider": "mcp",
        },
    )

    if is_progress_cancelled(progress_id):
        return []

    if progress_id and route_index is not None and route_total is not None:
        emit_progress(
            progress_id,
            "searching_flights",
            f"Checking {from_airport} <-> {to_airport} ({route_index}/{route_total})...",
        )

    legs = _build_legs(
        from_airport=from_airport,
        to_airport=to_airport,
        departure_date=departure_date,
        return_date=return_date,
    )
    initial_payload = mcp_search_flights(
        legs=legs,
        trip_type=_to_mcp_trip_type("round_trip"),
        passengers=_to_mcp_passengers(passengers),
        seat=seat_class,
        language=DEFAULT_LANGUAGE,
        currency=DEFAULT_CURRENCY,
        timeout_seconds=SEARCH_TOOL_TIMEOUT_SECONDS,
    )

    flight_choices: list[FlightInformation] = []
    for outbound_option in initial_payload.get("options") or []:
        outbound_handle = outbound_option.get("outbound_selection_handle")
        if not outbound_handle:
            continue

        follow_up_payload = mcp_search_return_flights(
            outbound_selection_handle=outbound_handle,
            legs=legs,
            trip_type=_to_mcp_trip_type("round_trip"),
            passengers=_to_mcp_passengers(passengers),
            seat=seat_class,
            language=DEFAULT_LANGUAGE,
            currency=DEFAULT_CURRENCY,
            timeout_seconds=SEARCH_TOOL_TIMEOUT_SECONDS,
        )

        for inbound_option in follow_up_payload.get("options") or []:
            adapted = _adapt_round_trip_option(
                outbound_option=outbound_option,
                inbound_option=inbound_option,
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date=departure_date,
                return_date=return_date,
            )
            if adapted is not None:
                flight_choices.append(adapted)

    logger.info(
        "Route search completed",
        extra={
            "from_airport": from_airport,
            "to_airport": to_airport,
            "departure_date": departure_date,
            "return_date": return_date,
            "trip": "round_trip",
            "results_count": len(flight_choices),
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
            "operation": "search_flights",
            "provider": "mcp",
        },
    )
    return flight_choices


def search_round_trip(
    flight_query: FlightQuery,
    *,
    max_concurrency: int = DEFAULT_MAX_ROUTE_SEARCH_CONCURRENCY,
    progress_id: str | None = None,
) -> list[FlightInformation]:
    from_airport = flight_query["from_airport"]
    to_airports = flight_query["to_airports"]
    departure_date = flight_query["departure_date"]
    return_date = flight_query["return_date"]
    seat_class = flight_query["seat_classes"]
    passengers = flight_query["passengers"]
    started_at = perf_counter()

    if not return_date:
        raise ValueError("Missing return_date for round_trip.")

    if progress_id:
        emit_progress(
            progress_id,
            "searching_flights",
            f"Searching round-trip flights for {len(to_airports)} destination(s) from {from_airport}...",
        )
        if is_progress_cancelled(progress_id):
            return []

    route_tasks = [
        {
            "label": f"{from_airport} <-> {to_airport} ({departure_date} / {return_date})",
            "display_label": f"{from_airport} <-> {to_airport}",
            "to_airport": to_airport,
            "progress_id": progress_id,
            "fn": lambda to_airport=to_airport, route_index=idx + 1, route_total=len(to_airports): _search_round_trip_route(
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date=departure_date,
                return_date=return_date,
                seat_class=seat_class,
                passengers=passengers,
                progress_id=progress_id,
                route_index=route_index,
                route_total=route_total,
            ),
        }
        for idx, to_airport in enumerate(to_airports)
    ]

    route_results = _collect_parallel_route_results(
        route_tasks,
        max_concurrency=max_concurrency,
    )
    flight_choices = [choice for route_result in route_results for choice in route_result]

    logger.info(
        "Flight search completed",
        extra={
            "from_airport": from_airport,
            "departure_date": departure_date,
            "return_date": return_date,
            "trip": "round_trip",
            "results_count": len(flight_choices),
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
        },
    )
    return flight_choices


def search_flights_node(state: AgentState) -> AgentState:
    flight_query = state.get("flight_query")

    if not flight_query:
        return {
            "flight_choices": None,
            "error_message": "Missing flight_query.",
        }

    try:
        trip = flight_query["trip"]
        progress_id = state.get("progress_id")

        if not flight_query["from_airport"] or not flight_query["to_airports"]:
            return {
                "flight_choices": None,
                "error_message": "Missing airports.",
            }

        if trip == "one_way":
            flight_choices = search_one_way(flight_query, progress_id=progress_id)
        elif trip == "round_trip":
            flight_choices = search_round_trip(flight_query, progress_id=progress_id)
        else:
            return {
                "flight_choices": None,
                "error_message": f"Unsupported trip type: {trip}",
            }

        return {
            "flight_choices": flight_choices,
            "error_message": None,
        }
    except FlightsMcpError as exc:
        logger.exception("MCP flight search failed for trip=%s", flight_query.get("trip"))
        return {
            "flight_choices": None,
            "error_message": f"Flight search failed: {exc}",
        }
    except Exception as exc:
        logger.exception("Flight search failed for trip=%s", flight_query.get("trip"))
        return {
            "flight_choices": None,
            "error_message": f"Flight search failed: {exc}",
        }
