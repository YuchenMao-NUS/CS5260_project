from concurrent.futures import ThreadPoolExecutor, as_completed
from smartflight.agent.state import *
from smartflight.agent.fast_flights import (
    FlightQuery as SearchFlightQuery,
    Passengers,
    SelectedFlight,
    create_query,
)
from smartflight.agent.fast_flights.browser_capture import fetch_booking_links_for_query
from smartflight.services.progress import emit_progress, is_progress_cancelled

import asyncio
import logging
from time import perf_counter

# 普通日志（带时间等）
logging.basicConfig(
    level=logging.INFO,  # 改成 DEBUG 可以看更详细日志
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
# ✅ 专门用于“最终输出”的 logger
result_logger = logging.getLogger("result")
result_logger.propagate = False  # ❗关键：不要走 root logger

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))  # ❗只输出内容
result_logger.addHandler(handler)
result_logger.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_MAX_BOOKING_URL_FETCH_CONCURRENCY = 5


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


def _format_segment_date(segment) -> str | None:
    departure = getattr(segment, "departure", None)
    date_value = getattr(departure, "date", None)
    if isinstance(date_value, list):
        date_value = tuple(date_value)
    if not isinstance(date_value, tuple) or len(date_value) != 3:
        return None
    year, month, day = date_value
    return f"{year:04d}-{month:02d}-{day:02d}"


def _build_selected_segments(itinerary) -> list[SelectedFlight]:
    selected_segments: list[SelectedFlight] = []
    segments = itinerary if isinstance(itinerary, list) else getattr(itinerary, "flights", []) or []
    for segment in segments:
        from_airport = getattr(getattr(segment, "from_airport", None), "code", None)
        to_airport = getattr(getattr(segment, "to_airport", None), "code", None)
        airline_code = getattr(segment, "flight_number_airline_code", None)
        flight_number = getattr(segment, "flight_number_numeric", None)
        flight_date = _format_segment_date(segment)
        if (
            not from_airport
            or not to_airport
            or not airline_code
            or not flight_number
            or not flight_date
        ):
            return []
        selected_segments.append(
            SelectedFlight(
                from_airport=from_airport,
                date=flight_date,
                to_airport=to_airport,
                airline_code=airline_code,
                flight_number=flight_number,
            )
        )
    return selected_segments


def _fetch_one_way_booking_url(
    *,
    from_airport: str,
    to_airport: str,
    departure_date: str,
    seat_class: str,
    passengers: int,
    flight_result,
) -> str | None:
    route_label = f"{from_airport} -> {to_airport} on {departure_date}"
    started_at = perf_counter()
    selected_segments = _build_selected_segments(flight_result)
    if not selected_segments:
        logger.info(
            "Skipping one-way booking URL fetch: route=%s, reason=no_selected_segments",
            route_label,
        )
        return None

    booking_query = create_query(
        flights=[
            SearchFlightQuery(
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
        selected_flight_segments=selected_segments,
    )
    logger.info(
        "Starting one-way booking URL fetch: route=%s, segments=%d",
        route_label,
        len(selected_segments),
    )
    try:
        booking_links = asyncio.run(
            fetch_booking_links_for_query(
                booking_query,
                headless=True,
                timeout_ms=300000,
            )
        )
    except Exception as exc:
        logger.warning(
            "One-way booking URL fetch failed: route=%s, elapsed=%.2fs, error=%s",
            route_label,
            perf_counter() - started_at,
            exc,
        )
        result_logger.warning("Final one-way booking fetch failed: %s", exc)
        return None
    booking_url = booking_links[0] if booking_links else None
    logger.info(
        "Finished one-way booking URL fetch: route=%s, found=%s, links=%d, elapsed=%.2fs",
        route_label,
        bool(booking_url),
        len(booking_links),
        perf_counter() - started_at,
    )
    return booking_url


def _fetch_round_trip_booking_url(
    *,
    from_airport: str,
    to_airport: str,
    departure_date: str,
    return_date: str,
    seat_class: str,
    passengers: int,
    tfu_token: str | None,
    outbound_option,
    inbound_option,
) -> str | None:
    route_label = f"{from_airport} <-> {to_airport} ({departure_date} / {return_date})"
    started_at = perf_counter()
    outbound_segments = _build_selected_segments(outbound_option)
    inbound_segments = _build_selected_segments(inbound_option)
    if not outbound_segments or not inbound_segments:
        logger.info(
            "Skipping round-trip booking URL fetch: route=%s, reason=missing_selected_segments",
            route_label,
        )
        return None

    booking_query = create_query(
        flights=[
            SearchFlightQuery(
                date=departure_date,
                from_airport=from_airport,
                to_airport=to_airport,
            ),
            SearchFlightQuery(
                date=return_date,
                from_airport=to_airport,
                to_airport=from_airport,
            ),
        ],
        seat=_get_seat(seat_class),
        trip="round-trip",
        passengers=Passengers(adults=passengers),
        language="en-US",
        currency="SGD",
        tfu=tfu_token,
        selected_outbound_segments=outbound_segments,
        selected_return_segments=inbound_segments,
    )
    logger.info(
        "Starting round-trip booking URL fetch: route=%s, outbound_segments=%d, inbound_segments=%d",
        route_label,
        len(outbound_segments),
        len(inbound_segments),
    )
    try:
        booking_links = asyncio.run(
            fetch_booking_links_for_query(
                booking_query,
                headless=True,
                timeout_ms=300000,
            )
        )
    except Exception as exc:
        logger.warning(
            "Round-trip booking URL fetch failed: route=%s, elapsed=%.2fs, error=%s",
            route_label,
            perf_counter() - started_at,
            exc,
        )
        result_logger.warning("Final round-trip booking fetch failed: %s", exc)
        return None
    booking_url = booking_links[0] if booking_links else None
    logger.info(
        "Finished round-trip booking URL fetch: route=%s, found=%s, links=%d, elapsed=%.2fs",
        route_label,
        bool(booking_url),
        len(booking_links),
        perf_counter() - started_at,
    )
    return booking_url

def _get_total_price(choice: FlightInformation) -> float:
    if choice["trip"] == "one_way":
        return float(choice["price"])
    return float(choice["price"]) + float(choice["price_2"] or 0.0)


def _get_total_duration(choice: FlightInformation) -> int:
    if choice["trip"] == "one_way":
        return int(choice["duration"])
    return int(choice["duration"]) + int(choice["duration_2"] or 0)


def _is_direct_effective(choice: FlightInformation) -> bool:
    """
    For one-way: direct means outbound is direct.
    For round-trip: direct means both outbound and inbound are direct.
    """
    if choice["trip"] == "one_way":
        return bool(choice["is_direct"])
    return bool(choice["is_direct"]) and bool(choice["is_direct_2"])


def _all_airlines(choice: FlightInformation) -> list[str]:
    airlines = list(choice.get("airlines") or [])
    airlines_2 = list(choice.get("airlines_2") or [])
    return airlines + airlines_2


def _matches_preferences(
    choice: FlightInformation,
    pref: FlightPreference,
) -> bool:
    """
    Hard filtering only.
    """
    total_price = _get_total_price(choice)
    total_duration = _get_total_duration(choice)

    direct_only = pref.get("direct_only")
    max_price = pref.get("max_price")
    min_price = pref.get("min_price")
    max_duration = pref.get("max_duration")
    min_duration = pref.get("min_duration")
    preferred_airlines = pref.get("preferred_airlines")

    # 1) direct_only is a hard constraint only when True
    if direct_only is True and not _is_direct_effective(choice):
        return False

    # 2) price hard constraints
    if max_price is not None and total_price > max_price:
        return False
    if min_price is not None and total_price < min_price:
        return False

    # 3) duration hard constraints
    if max_duration is not None and total_duration > max_duration:
        return False
    if min_duration is not None and total_duration < min_duration:
        return False

    # 4) preferred_airlines:
    # treat as a soft preference, not a hard constraint
    # so do NOT filter here

    return True


def _compute_rank_score(
    choice: FlightInformation,
    pref: FlightPreference,
    price_min: float,
    price_max: float,
    duration_min: int,
    duration_max: int,
) -> float:
    """
    Lower score = better.

    Ranking strategy:
    - cheaper is better
    - shorter is better
    - direct is better
    - airline preference match is better

    Normalization:
    - price_norm in [0,1]
    - duration_norm in [0,1]
    """

    total_price = _get_total_price(choice)
    total_duration = _get_total_duration(choice)
    is_direct = _is_direct_effective(choice)

    preferred_airlines = pref.get("preferred_airlines") or []
    airline_match = 0
    if preferred_airlines:
        choice_airlines = set(_all_airlines(choice))
        if any(a in choice_airlines for a in preferred_airlines):
            airline_match = 1

    # normalize price
    if price_max == price_min:
        price_norm = 0.0
    else:
        price_norm = (total_price - price_min) / (price_max - price_min)

    # normalize duration
    if duration_max == duration_min:
        duration_norm = 0.0
    else:
        duration_norm = (total_duration - duration_min) / (duration_max - duration_min)

    # penalties / bonuses
    direct_penalty = 0.0 if is_direct else 0.15
    airline_penalty = 0.0 if airline_match else (0.08 if preferred_airlines else 0.0)

    # weighted score
    # price is slightly more important than duration
    score = (
        0.55 * price_norm
        + 0.30 * duration_norm
        + direct_penalty
        + airline_penalty
    )

    return score


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

    started_at = perf_counter()
    trip = choice["trip"]
    route_label = f"{choice['from_airport']} -> {choice['to_airport']}"
    booking_url = None

    if progress_id and progress_label:
        emit_progress(
            progress_id,
            "formatting_results",
            f"Fetching booking link for {progress_label}...",
        )

    if choice["trip"] == "one_way":
        booking_url = _fetch_one_way_booking_url(
            from_airport=choice["from_airport"],
            to_airport=choice["to_airport"],
            departure_date=choice["departure_date"],
            seat_class=flight_query["seat_classes"],
            passengers=flight_query["passengers"],
            flight_result=choice.get("flights") or [],
        )
    elif choice["trip"] == "round_trip" and choice.get("return_date"):
        booking_url = _fetch_round_trip_booking_url(
            from_airport=choice["from_airport"],
            to_airport=choice["to_airport"],
            departure_date=choice["departure_date"],
            return_date=choice["return_date"],
            seat_class=flight_query["seat_classes"],
            passengers=flight_query["passengers"],
            tfu_token=choice.get("tfu_token"),
            outbound_option=choice.get("flights") or [],
            inbound_option=choice.get("flights_2") or [],
        )

    logger.info(
        "Attached booking URL: trip=%s, route=%s, found=%s, elapsed=%.2fs",
        trip,
        route_label,
        bool(booking_url),
        perf_counter() - started_at,
    )
    return {
        **choice,
        "booking_url": booking_url,
    }


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

    started_at = perf_counter()
    ordered_choices: list[FlightInformation | None] = [None] * len(choices)
    worker_count = _bounded_concurrency(len(choices), max_concurrency)
    completed_count = 0

    logger.info(
        "Starting parallel booking URL attachment: choices=%d, workers=%d",
        len(choices),
        worker_count,
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                _attach_booking_url,
                choice,
                flight_query,
                progress_id,
                f"{choice['from_airport']} -> {choice['to_airport']}",
            ): idx
            for idx, choice in enumerate(choices)
        }

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            choice = choices[idx]
            route_label = f"{choice['from_airport']} -> {choice['to_airport']}"
            try:
                ordered_choices[idx] = future.result()
                if progress_id:
                    completed_count += 1
                    emit_progress(
                        progress_id,
                        "formatting_results",
                        f"Finished booking link check for {choice['from_airport']} -> {choice['to_airport']} ({completed_count}/{len(choices)})...",
                    )
            except Exception as exc:
                logger.warning(
                    "Booking URL attachment failed: trip=%s, route=%s, error=%s",
                    choice["trip"],
                    route_label,
                    exc,
                )
                ordered_choices[idx] = choice

    attached_choices = [choice for choice in ordered_choices if choice is not None]
    success_count = sum(1 for choice in attached_choices if choice.get("booking_url"))
    logger.info(
        "Finished parallel booking URL attachment: choices=%d, attached=%d, workers=%d, elapsed=%.2fs",
        len(attached_choices),
        success_count,
        worker_count,
        perf_counter() - started_at,
    )
    return attached_choices


def _keep_best_option_per_destination(
    choices: list[FlightInformation],
) -> list[FlightInformation]:
    best_by_destination: dict[str, FlightInformation] = {}
    for choice in choices:
        to_airport = choice["to_airport"]
        if to_airport not in best_by_destination:
            best_by_destination[to_airport] = choice
    return list(best_by_destination.values())


def filter_flights_node(state: AgentState) -> AgentState:
    """
    Filter and sort flight_choices using flight_preference.

    Behavior:
    - If no flight_choices, return as-is
    - If no flight_preference, still sort by a default ranking:
        cheaper first, then shorter, then direct
    - Hard constraints:
        direct_only=True, price range, duration range
    - Soft preferences:
        preferred_airlines
    - If flight_query.is_multi_destination=True:
        keep only the best ticket for each destination
    """
    flight_choices = state.get("flight_choices")
    flight_preference = state.get("flight_preference") or {}
    flight_query = state.get("flight_query") or {}
    progress_id = state.get("progress_id")
    is_multi_destination = flight_query.get("is_multi_destination", False)

    if not flight_choices:
        return {
            "flight_choices": [],
            "error_message": None,
        }

    try:
        emit_progress(
            progress_id,
            "formatting_results",
            "Ranking and filtering flight results...",
        )

        # Step 1: hard filtering
        filtered_choices = [
            choice
            for choice in flight_choices
            if _matches_preferences(choice, flight_preference)
        ]

        # If everything got filtered out, return empty list instead of failing
        if not filtered_choices:
            return {
                # **state,
                "flight_choices": [],
                "error_message": None,
            }

        # Step 2: compute normalization range from filtered results
        prices = [_get_total_price(c) for c in filtered_choices]
        durations = [_get_total_duration(c) for c in filtered_choices]

        price_min = min(prices) if prices else 0.0
        price_max = max(prices) if prices else 0.0
        duration_min = min(durations) if durations else 0
        duration_max = max(durations) if durations else 0

        # Step 3: sort by score, then stable tie-breakers
        def sort_key(choice: FlightInformation):
            score = _compute_rank_score(
                choice=choice,
                pref=flight_preference,
                price_min=price_min,
                price_max=price_max,
                duration_min=duration_min,
                duration_max=duration_max,
            )

            total_price = _get_total_price(choice)
            total_duration = _get_total_duration(choice)
            is_direct = _is_direct_effective(choice)

            # lower is better for all tuple items
            return (
                score,
                total_price,
                total_duration,
                0 if is_direct else 1,
            )

        sorted_choices = sorted(filtered_choices, key=sort_key)

        # For destination recommendation flows, keep the top-ranked option per
        # destination before fetching booking URLs so we only fetch links for
        # the final shortlisted results.
        if is_multi_destination:
            sorted_choices = _keep_best_option_per_destination(sorted_choices)

        if flight_query and not is_progress_cancelled(progress_id):
            emit_progress(
                progress_id,
                "formatting_results",
                f"Fetching booking links for {len(sorted_choices)} option(s)...",
            )
            sorted_choices = _attach_booking_urls_in_parallel(
                sorted_choices,
                flight_query,
                max_concurrency=DEFAULT_MAX_BOOKING_URL_FETCH_CONCURRENCY,
                progress_id=progress_id,
            )

        result = {
            **state,
            "flight_choices": sorted_choices,
            "error_message": None,
        }

        result_logger.info("=== flight_query ===")
        for k, v in result["flight_query"].items():
            result_logger.info("  %s: %s", k, v)

        result_logger.info("\n=== flight_preference ===")
        for k, v in result["flight_preference"].items():
            result_logger.info("  %s: %s", k, v)

        if result["error_message"]:
            result_logger.warning("\n=== error ===\n  %s", result["error_message"])

        result_logger.info("\n=== flight_choices ===")

        flight_choices = result.get("flight_choices") or []

        if not flight_choices:
            result_logger.info("  (no results)")
        else:
            for i, choice in enumerate(flight_choices[:10], 1):
                # ===== 基本信息 =====
                header = (
                    f"\n--- Option {i} ---\n"
                    f"  trip: {choice['trip']}\n"
                    f"  route: {choice['from_airport']} -> {choice['to_airport']}\n"
                    f"  departure_date: {choice['departure_date']}"
                )

                if choice["return_date"]:
                    header += f"\n  return_date: {choice['return_date']}"

                result_logger.info(header)

                # ===== Outbound =====
                outbound_info = (
                    "\n  [Outbound]\n"
                    f"    airlines: {choice['airlines']}\n"
                    f"    price: {choice['price']}\n"
                    f"    duration: {choice['duration']} min\n"
                    f"    direct: {choice['is_direct']}"
                )
                result_logger.info(outbound_info)

                for j, f in enumerate(choice["flights"], 1):
                    result_logger.info(
                        "    Leg %d:\n"
                        "      %s -> %s\n"
                        "      depart: %s %s\n"
                        "      arrive: %s %s\n"
                        "      duration: %s min\n"
                        "      flight_no: %s",
                        j,
                        f.from_airport.code,
                        f.to_airport.code,
                        f.departure.date,
                        f.departure.time,
                        f.arrival.date,
                        f.arrival.time,
                        f.duration,
                        f.flight_number,
                    )

                # ===== Inbound =====
                if choice["trip"] == "round_trip":
                    inbound_info = (
                        "\n  [Inbound]\n"
                        f"    airlines: {choice['airlines_2']}\n"
                        f"    price: {choice['price_2']}\n"
                        f"    duration: {choice['duration_2']} min\n"
                        f"    direct: {choice['is_direct_2']}"
                    )
                    result_logger.info(inbound_info)

                    for j, f in enumerate(choice["flights_2"] or [], 1):
                        result_logger.info(
                            "    Leg %d:\n"
                            "      %s -> %s\n"
                            "      depart: %s %s\n"
                            "      arrive: %s %s\n"
                            "      duration: %s min\n"
                            "      flight_no: %s",
                            j,
                            f.from_airport.code,
                            f.to_airport.code,
                            f.departure.date,
                            f.departure.time,
                            f.arrival.date,
                            f.arrival.time,
                            f.duration,
                            f.flight_number,
                        )

        return result

    except Exception as e:
        return {
            # **state,
            "error_message": f"Flight filtering failed: {e}",
        }
