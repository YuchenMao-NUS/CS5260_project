"""Core typed models for requests, results, and booking selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SeatType = Literal["economy", "premium-economy", "business", "first"]
TripType = Literal["one-way", "round-trip", "multi-city"]


@dataclass(frozen=True)
class ContinuationHandle:
    """Opaque continuation state for follow-up search flows."""

    _value: str = field(repr=False)

    def is_empty(self) -> bool:
        return self._value == ""


@dataclass(frozen=True)
class TripLeg:
    date: str
    origin_airport: str
    destination_airport: str
    max_stops: int | None = None
    airline_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.date:
            raise ValueError("TripLeg.date must not be empty.")
        if not self.origin_airport or not self.destination_airport:
            raise ValueError("TripLeg airport codes must not be empty.")
        if self.origin_airport == self.destination_airport:
            raise ValueError("TripLeg origin and destination must differ.")
        if self.max_stops is not None and self.max_stops < 0:
            raise ValueError("TripLeg.max_stops must be non-negative.")


@dataclass(frozen=True)
class Passengers:
    adults: int = 1
    children: int = 0
    infants_in_seat: int = 0
    infants_on_lap: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.adults,
            self.children,
            self.infants_in_seat,
            self.infants_on_lap,
        )
        if any(count < 0 for count in counts):
            raise ValueError("Passenger counts must be non-negative.")
        if self.total <= 0:
            raise ValueError("At least one passenger is required.")
        if self.total > 9:
            raise ValueError("Google Flights supports at most 9 passengers.")
        if self.infants_on_lap > self.adults:
            raise ValueError("Each infant on lap requires an adult passenger.")

    @property
    def total(self) -> int:
        return self.adults + self.children + self.infants_in_seat + self.infants_on_lap


@dataclass(frozen=True)
class FlightSearchRequest:
    legs: tuple[TripLeg, ...]
    passengers: Passengers = field(default_factory=Passengers)
    seat: SeatType = "economy"
    trip_type: TripType = "one-way"
    language: str = "en-US"
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("FlightSearchRequest requires at least one trip leg.")
        if self.trip_type == "one-way" and len(self.legs) != 1:
            raise ValueError("One-way requests must contain exactly one leg.")
        if self.trip_type == "round-trip" and len(self.legs) != 2:
            raise ValueError("Round-trip requests must contain exactly two legs.")
        if self.trip_type == "multi-city" and len(self.legs) < 2:
            raise ValueError("Multi-city requests must contain at least two legs.")
        if not self.language:
            raise ValueError("FlightSearchRequest.language must not be empty.")
        if not self.currency:
            raise ValueError("FlightSearchRequest.currency must not be empty.")


@dataclass(frozen=True)
class SelectedSegment:
    origin_airport: str
    date: str
    destination_airport: str
    marketing_airline_code: str
    flight_number: str

    def __post_init__(self) -> None:
        if not all(
            [
                self.origin_airport,
                self.date,
                self.destination_airport,
                self.marketing_airline_code,
                self.flight_number,
            ]
        ):
            raise ValueError("SelectedSegment fields must not be empty.")


@dataclass(frozen=True)
class SelectedLeg:
    segments: tuple[SelectedSegment, ...]
    continuation: ContinuationHandle | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("SelectedLeg requires at least one selected segment.")


@dataclass(frozen=True)
class SelectedItinerary:
    legs: tuple[SelectedLeg, ...]

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("SelectedItinerary requires at least one selected leg.")


@dataclass(frozen=True)
class BookingRequest:
    search_request: FlightSearchRequest
    itinerary: SelectedItinerary

    def __post_init__(self) -> None:
        expected_legs = len(self.search_request.legs)
        actual_legs = len(self.itinerary.legs)
        if expected_legs != actual_legs:
            raise ValueError(
                "Selected itinerary leg count must match the original search request."
            )
        for search_leg, selected_leg in zip(
            self.search_request.legs, self.itinerary.legs, strict=True
        ):
            first_segment = selected_leg.segments[0]
            last_segment = selected_leg.segments[-1]
            if first_segment.origin_airport != search_leg.origin_airport:
                raise ValueError(
                    "Selected itinerary origin must match the original search leg."
                )
            if first_segment.date != search_leg.date:
                raise ValueError(
                    "Selected itinerary departure date must match the original search leg."
                )
            if last_segment.destination_airport != search_leg.destination_airport:
                raise ValueError(
                    "Selected itinerary destination must match the original search leg."
                )


@dataclass(frozen=True)
class Airport:
    code: str
    name: str


@dataclass(frozen=True)
class FlightSegment:
    origin: Airport
    destination: Airport
    departure_time: str
    arrival_time: str
    duration_minutes: int
    marketing_airline_code: str | None
    flight_number: str | None
    aircraft_type: str | None = None


@dataclass(frozen=True)
class CarbonData:
    typical_route_grams: int
    emitted_grams: int


@dataclass(frozen=True)
class FlightOption:
    kind: str
    price: int | None
    airlines: tuple[str, ...]
    segments: tuple[FlightSegment, ...]
    carbon: CarbonData | None = None
    continuation: ContinuationHandle | None = field(default=None, repr=False)


@dataclass(frozen=True)
class SearchResults:
    options: tuple[FlightOption, ...]
    selection_phase: Literal["initial", "follow-up"] = "initial"
