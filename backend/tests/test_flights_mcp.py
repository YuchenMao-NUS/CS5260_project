"""Focused tests for the local flights MCP integration layer."""

from pathlib import Path

import pytest

from smartflight.agent import search_flights as search_flights_module
from smartflight.services import flights_mcp


def test_search_one_way_adapts_mcp_option_shape(monkeypatch):
    """One-way MCP options should be normalized into the existing flight_choices shape."""

    def fake_search_flights(**kwargs):
        return {
            "selection_phase": "initial",
            "options": [
                {
                    "price": 420,
                    "airlines": ["Singapore Airlines"],
                    "segments": [
                        {
                            "origin_airport": "SIN",
                            "origin_airport_name": "Singapore",
                            "destination_airport": "TYO",
                            "destination_airport_name": "Tokyo",
                            "date": "2026-05-01",
                            "departure_time": "08:00",
                            "arrival_time": "16:00",
                            "duration_minutes": 480,
                            "marketing_airline_code": "SQ",
                            "flight_number": "638",
                            "aircraft_type": "A359",
                        }
                    ],
                    "selected_leg": {
                        "segments": [
                            {
                                "origin_airport": "SIN",
                                "date": "2026-05-01",
                                "destination_airport": "TYO",
                                "marketing_airline_code": "SQ",
                                "flight_number": "638",
                            }
                        ]
                    },
                    "outbound_selection_handle": None,
                    "selected_itinerary": None,
                }
            ],
        }

    monkeypatch.setattr(search_flights_module, "mcp_search_flights", fake_search_flights)

    result = search_flights_module.search_one_way(
        {
            "trip": "one_way",
            "from_airport": "SIN",
            "to_airports": ["TYO"],
            "departure_date": "2026-05-01",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        }
    )

    assert len(result) == 1
    choice = result[0]
    assert choice["trip"] == "one_way"
    assert choice["selected_leg"]["segments"][0]["flight_number"] == "638"
    assert choice["flights"][0]["from_airport"]["code"] == "SIN"
    assert choice["flights"][0]["flight_number"] == "SQ638"
    assert choice["duration"] == 480


def test_search_round_trip_combines_initial_and_follow_up_options(monkeypatch):
    """Round-trip MCP search should combine outbound and return selections into one choice."""

    def fake_search_flights(**kwargs):
        return {
            "selection_phase": "initial",
            "options": [
                {
                    "price": 500,
                    "airlines": ["Singapore Airlines"],
                    "segments": [
                        {
                            "origin_airport": "SIN",
                            "origin_airport_name": "Singapore",
                            "destination_airport": "TYO",
                            "destination_airport_name": "Tokyo",
                            "date": "2026-05-01",
                            "departure_time": "08:00",
                            "arrival_time": "16:00",
                            "duration_minutes": 480,
                            "marketing_airline_code": "SQ",
                            "flight_number": "638",
                            "aircraft_type": "A359",
                        }
                    ],
                    "selected_leg": {
                        "segments": [
                            {
                                "origin_airport": "SIN",
                                "date": "2026-05-01",
                                "destination_airport": "TYO",
                                "marketing_airline_code": "SQ",
                                "flight_number": "638",
                            }
                        ]
                    },
                    "outbound_selection_handle": "opaque-handle",
                }
            ],
        }

    def fake_search_return_flights(**kwargs):
        assert kwargs["outbound_selection_handle"] == "opaque-handle"
        return {
            "selection_phase": "follow-up",
            "options": [
                {
                    "price": 450,
                    "airlines": ["Singapore Airlines"],
                    "segments": [
                        {
                            "origin_airport": "TYO",
                            "origin_airport_name": "Tokyo",
                            "destination_airport": "SIN",
                            "destination_airport_name": "Singapore",
                            "date": "2026-05-08",
                            "departure_time": "10:00",
                            "arrival_time": "16:30",
                            "duration_minutes": 390,
                            "marketing_airline_code": "SQ",
                            "flight_number": "639",
                            "aircraft_type": "A359",
                        }
                    ],
                    "selected_itinerary": {
                        "legs": [
                            {
                                "segments": [
                                    {
                                        "origin_airport": "SIN",
                                        "date": "2026-05-01",
                                        "destination_airport": "TYO",
                                        "marketing_airline_code": "SQ",
                                        "flight_number": "638",
                                    }
                                ]
                            },
                            {
                                "segments": [
                                    {
                                        "origin_airport": "TYO",
                                        "date": "2026-05-08",
                                        "destination_airport": "SIN",
                                        "marketing_airline_code": "SQ",
                                        "flight_number": "639",
                                    }
                                ]
                            },
                        ]
                    },
                }
            ],
        }

    monkeypatch.setattr(search_flights_module, "mcp_search_flights", fake_search_flights)
    monkeypatch.setattr(
        search_flights_module,
        "mcp_search_return_flights",
        fake_search_return_flights,
    )

    result = search_flights_module.search_round_trip(
        {
            "trip": "round_trip",
            "from_airport": "SIN",
            "to_airports": ["TYO"],
            "departure_date": "2026-05-01",
            "return_date": "2026-05-08",
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        }
    )

    assert len(result) == 1
    choice = result[0]
    assert choice["trip"] == "round_trip"
    assert choice["outbound_selection_handle"] == "opaque-handle"
    assert choice["selected_itinerary"]["legs"][1]["segments"][0]["flight_number"] == "639"
    assert choice["flights_2"][0]["to_airport"]["code"] == "SIN"
    assert choice["price"] == 500.0
    assert choice["price_2"] == 450.0


def test_call_tool_rejects_missing_local_repo(monkeypatch):
    """The MCP wrapper should fail fast with a clear local-path error."""

    monkeypatch.setattr(flights_mcp.settings, "FLIGHTS_SEARCH_REPO", Path("missing-repo"))
    monkeypatch.setattr(flights_mcp.settings, "FLIGHTS_SEARCH_SRC", Path("missing-repo/src"))

    with pytest.raises(flights_mcp.FlightsMcpError) as exc:
        flights_mcp.call_tool("server_info", {})

    assert exc.value.code == "mcp_server_missing"
