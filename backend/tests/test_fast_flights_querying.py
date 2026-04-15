"""Regression tests for selected-flight query serialization and parsing."""

import json

from smartflight.agent.fast_flights import FlightQuery, Passengers, SelectedFlight, create_query
from smartflight.agent.fast_flights.parser import parse_js


def test_one_way_selected_flight_changes_tfs_and_is_retained():
    base_query = create_query(
        flights=[
            FlightQuery(
                date="2026-05-11",
                from_airport="SIN",
                to_airport="JHB",
            )
        ],
        seat="economy",
        trip="one-way",
        passengers=Passengers(adults=1),
        language="en-US",
        currency="SGD",
    )

    selected_query = create_query(
        flights=[
            FlightQuery(
                date="2026-05-11",
                from_airport="SIN",
                to_airport="JHB",
            )
        ],
        seat="economy",
        trip="one-way",
        passengers=Passengers(adults=1),
        language="en-US",
        currency="SGD",
        selected_flight_segments=[
            SelectedFlight(
                from_airport="SIN",
                date="2026-05-11",
                to_airport="JHB",
                airline_code="MH",
                flight_number="624",
            )
        ],
    )

    assert selected_query.selected_flight is not None
    assert len(selected_query.selected_flight) == 1
    assert selected_query.to_str() != base_query.to_str()
    assert "Gjs" in selected_query.to_str()
    assert "Gho" in base_query.to_str()


def test_parse_js_treats_missing_hour_as_midnight():
    single_flight = [None] * 23
    single_flight[3] = "SIN"
    single_flight[4] = "Singapore Changi Airport"
    single_flight[5] = "Tokyo Narita Airport"
    single_flight[6] = "NRT"
    single_flight[8] = [7, 30]
    single_flight[10] = [None, 15]
    single_flight[11] = 465
    single_flight[17] = "Boeing 787"
    single_flight[20] = [2026, 5, 17]
    single_flight[21] = [2026, 5, 17]
    single_flight[22] = ["SQ", "638", None, "Singapore Airlines"]

    flight = [
        "SQ",
        ["Singapore Airlines"],
        [single_flight],
    ]
    row = [
        flight,
        [[None, 512], "tfu-token"],
    ]

    payload = [None] * 8
    payload[2] = [[row]]
    payload[7] = [None, [[], []]]

    parsed = parse_js(f"data:{json.dumps(payload)},")

    assert len(parsed) == 1
    segment = parsed[0].flights[0]
    assert segment.departure.date == (2026, 5, 17)
    assert segment.departure.time == (7, 30)
    assert segment.arrival.date == (2026, 5, 17)
    assert segment.arrival.time == (0, 15)
