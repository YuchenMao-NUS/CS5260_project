from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter, sleep

import logging

from smartflight.agent.fast_flights import (
    FlightQuery as FastFlightQuery,
    Passengers,
    create_query,
    get_flights,
)
from smartflight.agent.state import AgentState, FlightInformation, FlightQuery

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUTE_SEARCH_CONCURRENCY = 10


def _get_flights_with_retry(query, route_label: str, max_retries: int = 3, delay: float = 1.0):
    for attempt in range(max_retries):
        try:
            return get_flights(query)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    "Retrying flight search for %s after attempt %d/%d failed: %s",
                    route_label,
                    attempt + 1,
                    max_retries,
                    e,
                )
                sleep(delay)
            else:
                logger.error(
                    "Flight search failed for %s after %d attempts: %s",
                    route_label,
                    max_retries,
                    e,
                )
                raise


def _get_seat(seat_class: str) -> str:
    seat_map = {
        "economy": "economy",
        "business": "business",
        "first": "first",
        "premium-economy": "premium-economy",
    }
    if seat_class not in seat_map:
        raise ValueError(f"Unsupported seat class: {seat_class}")
    return seat_map[seat_class]


def _bounded_concurrency(task_count: int, max_concurrency: int) -> int:
    return max(1, min(task_count, max_concurrency))


def _collect_parallel_route_results(route_tasks, *, max_concurrency: int):
    if not route_tasks:
        return []

    ordered_results = [None] * len(route_tasks)
    worker_count = _bounded_concurrency(len(route_tasks), max_concurrency)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(task["fn"]): idx for idx, task in enumerate(route_tasks)
        }

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            route_label = route_tasks[idx]["label"]
            try:
                ordered_results[idx] = future.result()
            except Exception as e:
                logger.warning(
                    "Skipping route %s due to error: %s",
                    route_label,
                    e,
                )
                ordered_results[idx] = []

    return ordered_results


def _search_one_way_route(
    from_airport: str,
    to_airport: str,
    departure_date: str,
    seat_class: str,
    passengers: int,
) -> list[FlightInformation]:
    route_label = f"{from_airport} -> {to_airport} on {departure_date}"
    started_at = perf_counter()

    query = create_query(
        flights=[
            FastFlightQuery(
                date=departure_date,
                from_airport=from_airport,
                to_airport=to_airport,
            )
        ],
        seat=_get_seat(seat_class),
        trip="one-way",
        passengers=Passengers(adults=passengers),
        language="en-US",
        currency="SGD",
    )

    results = _get_flights_with_retry(query, route_label) or []
    flight_choices: list[FlightInformation] = []

    for result in results:
        outbound_flights = result.flights or []
        outbound_duration = sum(f.duration for f in outbound_flights)

        flight_choices.append(
            {
                "trip": "one_way",
                "from_airport": from_airport,
                "to_airport": to_airport,
                "departure_date": departure_date,
                "return_date": None,
                "booking_url": None,
                "tfu_token": None,
                "is_direct": len(outbound_flights) == 1,
                "airlines": list(result.airlines),
                "price": float(result.price),
                "duration": outbound_duration,
                "flights": outbound_flights,
                "is_direct_2": None,
                "airlines_2": None,
                "price_2": None,
                "duration_2": None,
                "flights_2": None,
            }
        )

    logger.info(
        "Completed one-way route search: %s, results=%d, elapsed=%.2fs",
        route_label,
        len(flight_choices),
        perf_counter() - started_at,
    )
    return flight_choices


def search_one_way(
    flight_query: FlightQuery,
    *,
    max_concurrency: int = DEFAULT_MAX_ROUTE_SEARCH_CONCURRENCY,
) -> list[FlightInformation]:
    """
    Search one-way flights and return normalized FlightInformation list.
    """
    from_airport = flight_query["from_airport"]
    to_airports = flight_query["to_airports"]
    departure_date = flight_query["departure_date"]
    seat_class = flight_query["seat_classes"]
    passengers = flight_query["passengers"]
    started_at = perf_counter()

    logger.info(
        "Starting one-way flight search: from=%s, destinations=%d, departure_date=%s, seat=%s, passengers=%s, workers=%d",
        from_airport,
        len(to_airports),
        departure_date,
        seat_class,
        passengers,
        _bounded_concurrency(len(to_airports), max_concurrency),
    )

    route_tasks = [
        {
            "label": f"{from_airport} -> {to_airport} on {departure_date}",
            "fn": lambda to_airport=to_airport: _search_one_way_route(
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date=departure_date,
                seat_class=seat_class,
                passengers=passengers,
            ),
        }
        for to_airport in to_airports
    ]

    route_results = _collect_parallel_route_results(
        route_tasks,
        max_concurrency=max_concurrency,
    )
    flight_choices = [
        choice for route_result in route_results for choice in route_result
    ]

    logger.info(
        "Finished one-way flight search: from=%s, destinations=%d, total_choices=%d, elapsed=%.2fs",
        from_airport,
        len(to_airports),
        len(flight_choices),
        perf_counter() - started_at,
    )

    return flight_choices


def _search_round_trip_route(
    from_airport: str,
    to_airport: str,
    departure_date: str,
    return_date: str,
    seat_class: str,
    passengers: int,
) -> list[FlightInformation]:
    route_label = f"{from_airport} <-> {to_airport} ({departure_date} / {return_date})"
    started_at = perf_counter()

    flights = [
        FastFlightQuery(
            date=departure_date,
            from_airport=from_airport,
            to_airport=to_airport,
        ),
        FastFlightQuery(
            date=return_date,
            from_airport=to_airport,
            to_airport=from_airport,
        ),
    ]

    step1_query = create_query(
        flights=flights,
        seat=_get_seat(seat_class),
        trip="round-trip",
        passengers=Passengers(adults=passengers),
        language="en-US",
        currency="SGD",
    )

    step1_results = _get_flights_with_retry(step1_query, route_label) or []
    if not step1_results:
        logger.info(
            "Completed round-trip route search: %s, outbound_options=0, combinations=0, elapsed=%.2fs",
            route_label,
            perf_counter() - started_at,
        )
        return []

    flight_choices: list[FlightInformation] = []

    for outbound_option in step1_results:
        outbound_flights = outbound_option.flights or []
        if not outbound_flights:
            continue

        outbound_duration = sum(f.duration for f in outbound_flights)

        selected_first_leg = outbound_flights[0]
        selected_token = outbound_option.tfu_token
        selected_outbound_airline_code = selected_first_leg.flight_number_airline_code
        selected_outbound_flight_number = selected_first_leg.flight_number_numeric

        if (
            not selected_token
            or not selected_outbound_airline_code
            or not selected_outbound_flight_number
        ):
            continue

        step2_query = create_query(
            flights=flights,
            seat=_get_seat(seat_class),
            trip="round-trip",
            passengers=Passengers(adults=passengers),
            language="en-US",
            currency="SGD",
            tfu=selected_token,
            selected_outbound_airline_code=selected_outbound_airline_code,
            selected_outbound_flight_number=selected_outbound_flight_number,
        )

        step2_results = _get_flights_with_retry(
            step2_query,
            f"{route_label} [selected outbound]",
        ) or []

        for inbound_option in step2_results:
            inbound_flights = inbound_option.flights or []
            if not inbound_flights:
                continue

            inbound_duration = sum(f.duration for f in inbound_flights)

            flight_choices.append(
                {
                    "trip": "round_trip",
                    "from_airport": from_airport,
                    "to_airport": to_airport,
                    "departure_date": departure_date,
                    "return_date": return_date,
                    "booking_url": None,
                    "tfu_token": selected_token,
                    "is_direct": len(outbound_flights) == 1,
                    "airlines": list(outbound_option.airlines),
                    "price": float(outbound_option.price),
                    "duration": outbound_duration,
                    "flights": outbound_flights,
                    "is_direct_2": len(inbound_flights) == 1,
                    "airlines_2": list(inbound_option.airlines),
                    "price_2": float(inbound_option.price),
                    "duration_2": inbound_duration,
                    "flights_2": inbound_flights,
                }
            )

    logger.info(
        "Completed round-trip route search: %s, outbound_options=%d, combinations=%d, elapsed=%.2fs",
        route_label,
        len(step1_results),
        len(flight_choices),
        perf_counter() - started_at,
    )
    return flight_choices


def search_round_trip(
    flight_query: FlightQuery,
    *,
    max_concurrency: int = DEFAULT_MAX_ROUTE_SEARCH_CONCURRENCY,
) -> list[FlightInformation]:
    """
    Search round-trip flights and return normalized FlightInformation list.
    """
    from_airport = flight_query["from_airport"]
    to_airports = flight_query["to_airports"]
    departure_date = flight_query["departure_date"]
    return_date = flight_query["return_date"]
    seat_class = flight_query["seat_classes"]
    passengers = flight_query["passengers"]
    started_at = perf_counter()

    if not return_date:
        raise ValueError("Missing return_date for round_trip.")

    logger.info(
        "Starting round-trip flight search: from=%s, destinations=%d, departure_date=%s, return_date=%s, seat=%s, passengers=%s, workers=%d",
        from_airport,
        len(to_airports),
        departure_date,
        return_date,
        seat_class,
        passengers,
        _bounded_concurrency(len(to_airports), max_concurrency),
    )

    route_tasks = [
        {
            "label": f"{from_airport} <-> {to_airport} ({departure_date} / {return_date})",
            "fn": lambda to_airport=to_airport: _search_round_trip_route(
                from_airport=from_airport,
                to_airport=to_airport,
                departure_date=departure_date,
                return_date=return_date,
                seat_class=seat_class,
                passengers=passengers,
            ),
        }
        for to_airport in to_airports
    ]

    route_results = _collect_parallel_route_results(
        route_tasks,
        max_concurrency=max_concurrency,
    )
    flight_choices = [
        choice for route_result in route_results for choice in route_result
    ]

    logger.info(
        "Finished round-trip flight search: from=%s, destinations=%d, total_choices=%d, elapsed=%.2fs",
        from_airport,
        len(to_airports),
        len(flight_choices),
        perf_counter() - started_at,
    )

    return flight_choices


def search_flights_node(state: AgentState) -> AgentState:
    """
    Dispatch by trip type.
    """
    flight_query = state.get("flight_query")

    if not flight_query:
        return {
            "flight_choices": None,
            "error_message": "Missing flight_query.",
        }

    try:
        trip = flight_query["trip"]

        if not flight_query["from_airport"] or not flight_query["to_airports"]:
            return {
                "flight_choices": None,
                "error_message": "Missing airports.",
            }

        if trip == "one_way":
            flight_choices = search_one_way(flight_query)
        elif trip == "round_trip":
            flight_choices = search_round_trip(flight_query)
        else:
            return {
                "flight_choices": None,
                "error_message": f"Unsupported trip type: {trip}",
            }

        return {
            "flight_choices": flight_choices,
            "error_message": None,
        }

    except Exception as e:
        logger.exception("Flight search failed for trip=%s", flight_query.get("trip"))
        return {
            "flight_choices": None,
            "error_message": f"Flight search failed: {e}",
        }
