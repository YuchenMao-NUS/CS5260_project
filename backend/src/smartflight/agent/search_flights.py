from smartflight.agent.state import *
from smartflight.agent.fast_flights import (
    FlightQuery as FlightQuery,
    Passengers,
    create_query,
    get_flights,
)

import logging
import time

logger = logging.getLogger(__name__)


def _get_flights_with_retry(query, max_retries=3, delay=1.0):
    for attempt in range(max_retries):
        try:
            return get_flights(query)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning("Error fetching flights (attempt %d/%d): %s. Retrying in %ss...", attempt + 1, max_retries, e, delay)
                time.sleep(delay)
            else:
                logger.error("Failed to fetch flights after %d attempts: %s", max_retries, e)
                raise e

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


def search_one_way(flight_query: FlightQuery) -> list[FlightInformation]:
    """
    Search one-way flights and return normalized FlightInformation list.
    """
    from_airport = flight_query["from_airport"]
    to_airports = flight_query["to_airports"]
    departure_date = flight_query["departure_date"]
    seat_class = flight_query["seat_classes"]
    passengers = flight_query["passengers"]

    logger.info(
        "Starting one-way flight search: from=%s, to=%s, departure_date=%s, seat=%s, passengers=%s",
        from_airport,
        to_airports,
        departure_date,
        seat_class,
        passengers,
    )

    flight_choices: list[FlightInformation] = []

    for to_airport in to_airports:
        try:
            logger.info(
                "Searching one-way route: %s -> %s on %s",
                from_airport,
                to_airport,
                departure_date,
            )

            query = create_query(
                flights=[
                    FlightQuery(
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

            logger.debug("One-way query built for %s -> %s", from_airport, to_airport)

            results = _get_flights_with_retry(query) or []

            logger.info(
                "Received %d one-way results for %s -> %s",
                len(results),
                from_airport,
                to_airport,
            )

        except Exception as e:
            logger.warning(
                "Skipping one-way route %s -> %s due to error: %s",
                from_airport,
                to_airport,
                e,
                exc_info=True,
            )
            continue

        for idx, r in enumerate(results, start=1):
            outbound_flights = r.flights or []
            outbound_duration = sum(f.duration for f in outbound_flights)

            info: FlightInformation = {
                "trip": "one_way",
                "from_airport": from_airport,
                "to_airport": to_airport,
                "departure_date": departure_date,
                "return_date": None,
                "booking_url": None,
                "tfu_token": None,
                "is_direct": len(outbound_flights) == 1,
                "airlines": list(r.airlines),
                "price": float(r.price),
                "duration": outbound_duration,
                "flights": outbound_flights,
                "is_direct_2": None,
                "airlines_2": None,
                "price_2": None,
                "duration_2": None,
                "flights_2": None,
            }
            flight_choices.append(info)

            logger.debug(
                "Added one-way option #%d for %s -> %s: price=%s, duration=%s, direct=%s, airlines=%s",
                idx,
                from_airport,
                to_airport,
                info["price"],
                info["duration"],
                info["is_direct"],
                info["airlines"],
            )

    logger.info(
        "Finished one-way flight search: total_choices=%d",
        len(flight_choices),
    )

    return flight_choices


def search_round_trip(flight_query: FlightQuery) -> list[FlightInformation]:
    """
    Search round-trip flights and return normalized FlightInformation list.

    Logic:
    1. search outbound options
    2. for each outbound option, search tied return options
    3. combine outbound + inbound into one FlightInformation
    """
    from_airport = flight_query["from_airport"]
    to_airports = flight_query["to_airports"]
    departure_date = flight_query["departure_date"]
    return_date = flight_query["return_date"]
    seat_class = flight_query["seat_classes"]
    passengers = flight_query["passengers"]

    if not return_date:
        raise ValueError("Missing return_date for round_trip.")

    logger.info(
        "Starting round-trip flight search: from=%s, to=%s, departure_date=%s, return_date=%s, seat=%s, passengers=%s",
        from_airport,
        to_airports,
        departure_date,
        return_date,
        seat_class,
        passengers,
    )

    flight_choices: list[FlightInformation] = []

    for to_airport in to_airports:
        try:
            logger.info(
                "Searching round-trip route: %s -> %s -> %s, departure=%s, return=%s",
                from_airport,
                to_airport,
                from_airport,
                departure_date,
                return_date,
            )

            flights = [
                FlightQuery(
                    date=departure_date,
                    from_airport=from_airport,
                    to_airport=to_airport,
                ),
                FlightQuery(
                    date=return_date,
                    from_airport=to_airport,
                    to_airport=from_airport,
                ),
            ]

            # Step 1: outbound options
            step1_query = create_query(
                flights=flights,
                seat=_get_seat(seat_class),
                trip="round-trip",
                passengers=Passengers(adults=passengers),
                language="en-US",
                currency="SGD",
            )

            logger.debug(
                "Round-trip step1 query built for %s <-> %s",
                from_airport,
                to_airport,
            )

            step1_results = _get_flights_with_retry(step1_query) or []

            logger.info(
                "Received %d outbound options for round-trip route %s <-> %s",
                len(step1_results),
                from_airport,
                to_airport,
            )

            if not step1_results:
                logger.info(
                    "No outbound options found for round-trip route %s <-> %s",
                    from_airport,
                    to_airport,
                )
                continue

            for outbound_idx, outbound_option in enumerate(step1_results, start=1):
                outbound_flights = outbound_option.flights or []
                if not outbound_flights:
                    logger.debug(
                        "Skipping outbound option #%d for %s <-> %s: empty outbound_flights",
                        outbound_idx,
                        from_airport,
                        to_airport,
                    )
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
                    logger.debug(
                        "Skipping outbound option #%d for %s <-> %s: missing tfu/flight_number info "
                        "(token=%s, airline_code=%s, flight_number=%s)",
                        outbound_idx,
                        from_airport,
                        to_airport,
                        selected_token,
                        selected_outbound_airline_code,
                        selected_outbound_flight_number,
                    )
                    continue

                logger.debug(
                    "Round-trip step2 query for outbound option #%d on %s <-> %s: token=%s, airline_code=%s, flight_number=%s",
                    outbound_idx,
                    from_airport,
                    to_airport,
                    selected_token,
                    selected_outbound_airline_code,
                    selected_outbound_flight_number,
                )

                # Step 2: inbound options tied to selected outbound
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

                step2_results = _get_flights_with_retry(step2_query) or []

                logger.info(
                    "Received %d inbound options for outbound option #%d on route %s <-> %s",
                    len(step2_results),
                    outbound_idx,
                    from_airport,
                    to_airport,
                )

                if not step2_results:
                    logger.debug(
                        "No inbound options found for outbound option #%d on route %s <-> %s",
                        outbound_idx,
                        from_airport,
                        to_airport,
                    )
                    continue

                for inbound_idx, inbound_option in enumerate(step2_results, start=1):
                    inbound_flights = inbound_option.flights or []
                    if not inbound_flights:
                        logger.debug(
                            "Skipping inbound option #%d (outbound #%d) for %s <-> %s: empty inbound_flights",
                            inbound_idx,
                            outbound_idx,
                            from_airport,
                            to_airport,
                        )
                        continue

                    inbound_duration = sum(f.duration for f in inbound_flights)

                    info: FlightInformation = {
                        "trip": "round_trip",
                        "from_airport": from_airport,
                        "to_airport": to_airport,
                        "departure_date": departure_date,
                        "return_date": return_date,
                        "booking_url": None,
                        "tfu_token": selected_token,
                        # outbound ticket
                        "is_direct": len(outbound_flights) == 1,
                        "airlines": list(outbound_option.airlines),
                        "price": float(outbound_option.price),
                        "duration": outbound_duration,
                        "flights": outbound_flights,
                        # inbound ticket
                        "is_direct_2": len(inbound_flights) == 1,
                        "airlines_2": list(inbound_option.airlines),
                        "price_2": float(inbound_option.price),
                        "duration_2": inbound_duration,
                        "flights_2": inbound_flights,
                    }
                    flight_choices.append(info)

                    logger.debug(
                        "Added round-trip option: route=%s <-> %s, outbound_idx=%d, inbound_idx=%d, "
                        "outbound_price=%s, inbound_price=%s, outbound_duration=%s, inbound_duration=%s",
                        from_airport,
                        to_airport,
                        outbound_idx,
                        inbound_idx,
                        info["price"],
                        info["price_2"],
                        info["duration"],
                        info["duration_2"],
                    )

        except Exception as e:
            logger.warning(
                "Skipping round-trip route %s <-> %s due to error: %s",
                from_airport,
                to_airport,
                e,
                exc_info=True,
            )
            continue

    logger.info(
        "Finished round-trip flight search: total_choices=%d",
        len(flight_choices),
    )

    return flight_choices


def search_flights_node(state: AgentState) -> AgentState:
    """
    Dispatch by trip type.
    """
    flight_query = state.get("flight_query")

    if not flight_query:
        return {
            **state,
            "flight_choices": None,
            "error_message": "Missing flight_query.",
        }

    try:
        trip = flight_query["trip"]

        if not flight_query["from_airport"] or not flight_query["to_airports"]:
            return {
                **state,
                "flight_choices": None,
                "error_message": "Missing airports.",
            }

        if trip == "one_way":
            flight_choices = search_one_way(flight_query)
        elif trip == "round_trip":
            flight_choices = search_round_trip(flight_query)
        else:
            return {
                **state,
                "flight_choices": None,
                "error_message": f"Unsupported trip type: {trip}",
            }

        return {
            **state,
            "flight_choices": flight_choices,
            "error_message": None,
        }

    except Exception as e:
        return {
            **state,
            "flight_choices": None,
            "error_message": f"Flight search failed: {e}",
        }
