"""Pydantic schemas for the MCP tool boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SeatType = Literal["economy", "premium-economy", "business", "first"]
TripType = Literal["one-way", "round-trip", "multi-city"]


class McpSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TripLegInput(McpSchema):
    date: str
    origin_airport: str
    destination_airport: str
    max_stops: int | None = None
    airline_codes: list[str] = Field(default_factory=list)


class PassengersInput(McpSchema):
    adults: int = 1
    children: int = 0
    infants_in_seat: int = 0
    infants_on_lap: int = 0


class SelectedSegmentModel(McpSchema):
    origin_airport: str
    date: str
    destination_airport: str
    marketing_airline_code: str
    flight_number: str


class SelectedLegModel(McpSchema):
    segments: list[SelectedSegmentModel]


class SelectedItineraryModel(McpSchema):
    legs: list[SelectedLegModel]


class ResolveBookingUrlsResponse(McpSchema):
    booking_urls: list[str]


class FlightSegmentOutput(McpSchema):
    origin_airport: str
    origin_airport_name: str
    destination_airport: str
    destination_airport_name: str
    date: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    marketing_airline_code: str | None
    flight_number: str | None
    aircraft_type: str | None = None


class SearchFlightOptionOutput(McpSchema):
    kind: str
    price: int | None
    airlines: list[str]
    segment_count: int
    stop_count: int
    segments: list[FlightSegmentOutput]
    selected_leg: SelectedLegModel | None = None
    selected_itinerary: SelectedItineraryModel | None = None
    outbound_selection_handle: str | None = None
    selection_unavailable_reason: str | None = None


class SearchFlightsResponse(McpSchema):
    selection_phase: Literal["initial", "follow-up"]
    options: list[SearchFlightOptionOutput]


class ServerInfoResponse(McpSchema):
    server_name: str
    version: str
    transport: str
    tools: list[str]
