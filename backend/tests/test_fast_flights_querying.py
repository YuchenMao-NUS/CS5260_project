"""Regression tests for selected-flight query serialization."""

from smartflight.agent.fast_flights import FlightQuery, Passengers, SelectedFlight, create_query


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
