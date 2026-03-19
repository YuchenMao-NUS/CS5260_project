from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime as Datetime
from typing import Literal, Optional, Union

from .pb.flights_pb2 import Airport, FlightData, Info, Passenger, Seat, Trip
from .types import Currency, Language, SeatType, TripType


@dataclass
class SelectedOutbound:
    from_airport: str
    date: str
    to_airport: str
    airline_code: str
    flight_number: str


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            break
    return bytes(out)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    i = offset
    while i < len(data):
        b = data[i]
        result |= (b & 0x7F) << shift
        i += 1
        if (b & 0x80) == 0:
            return result, i
        shift += 7
    raise ValueError("incomplete varint")


def _wire_str(field_no: int, value: str) -> bytes:
    payload = value.encode("utf-8")
    return bytes([(field_no << 3) | 2]) + _encode_varint(len(payload)) + payload


def _encode_selected_outbound_field(s: SelectedOutbound) -> bytes:
    payload = b"".join(
        [
            _wire_str(1, s.from_airport),
            _wire_str(2, s.date),
            _wire_str(3, s.to_airport),
            _wire_str(5, s.airline_code),
            _wire_str(6, s.flight_number),
        ]
    )
    # FlightData field #4, length-delimited
    return bytes([(4 << 3) | 2]) + _encode_varint(len(payload)) + payload


def _inject_selected_outbound(info_bytes: bytes, selected: SelectedOutbound) -> bytes:
    i = 0
    out = bytearray()
    injected = False

    while i < len(info_bytes):
        tag_pos = i
        tag, i = _decode_varint(info_bytes, i)
        field_no = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:
            _, i = _decode_varint(info_bytes, i)
            out.extend(info_bytes[tag_pos:i])
            continue

        if wire_type != 2:
            out.extend(info_bytes[tag_pos:])
            break

        length, after_len = _decode_varint(info_bytes, i)
        value_start = after_len
        value_end = value_start + length
        if value_end > len(info_bytes):
            out.extend(info_bytes[tag_pos:])
            break

        if field_no == 3 and not injected:
            original_flight_data = info_bytes[value_start:value_end]
            enriched_flight_data = (
                original_flight_data + _encode_selected_outbound_field(selected)
            )
            out.extend(_encode_varint(tag))
            out.extend(_encode_varint(len(enriched_flight_data)))
            out.extend(enriched_flight_data)
            injected = True
        else:
            out.extend(info_bytes[tag_pos:value_end])
        i = value_end

    return bytes(out)


@dataclass
class Query:
    """A query containing `?tfs` data."""

    flight_data: list[FlightData]
    seat: Seat
    trip: Trip
    passengers: list[Passenger]
    language: str
    currency: str
    tfu: str | None = None
    selected_outbound: SelectedOutbound | None = None

    def pb(self) -> Info:
        """(internal) Protobuf data. (`Info`)"""
        return Info(
            data=self.flight_data,
            seat=self.seat,
            trip=self.trip,
            passengers=self.passengers,
        )

    def to_bytes(self) -> bytes:
        """Convert this query to bytes."""
        data = self.pb().SerializeToString()
        if (
            self.tfu
            and self.trip == Trip.ROUND_TRIP
            and self.selected_outbound is not None
        ):
            return _inject_selected_outbound(data, self.selected_outbound)
        return data

    def to_str(self) -> str:
        """Convert this query to a string."""
        return b64encode(self.to_bytes()).decode("utf-8")

    def url(self) -> str:
        """Get the URL for this query.

        This is generally used for debugging purposes.
        """
        url = (
            "https://www.google.com/travel/flights/search?tfs="
            + self.to_str()
            + "&hl="
            + self.language
            + "&curr="
            + self.currency
        )
        if self.tfu:
            url += "&tfu=" + self.tfu
        return url

    def params(self) -> dict[str, str]:
        """Create `params` in dictionary form."""
        params = {"tfs": self.to_str(), "hl": self.language, "curr": self.currency}
        if self.tfu:
            params["tfu"] = self.tfu
        return params

    def __repr__(self) -> str:
        return "Query(...)"


@dataclass
class FlightQuery:
    date: str | Datetime
    from_airport: str
    to_airport: str
    max_stops: int | None = None
    airlines: list[str] | None = None

    def pb(self) -> FlightData:
        if isinstance(self.date, str):
            date = self.date
        else:
            date = self.date.strftime("%Y-%m-%d")

        return FlightData(
            date=date,
            from_airport=Airport(airport=self.from_airport),
            to_airport=Airport(airport=self.to_airport),
            max_stops=self.max_stops,
            airlines=self.airlines,
        )

    def _setmaxstops(self, m: int | None = None) -> "FlightQuery":
        if m is not None:
            self.max_stops = m

        return self


class Passengers:
    def __init__(
        self,
        *,
        adults: int = 0,
        children: int = 0,
        infants_in_seat: int = 0,
        infants_on_lap: int = 0,
    ):
        assert sum((adults, children, infants_in_seat, infants_on_lap)) <= 9, (
            "Too many passengers (> 9)"
        )
        assert infants_on_lap <= adults, (
            "Must have at least one adult per infant on lap"
        )

        self.adults = adults
        self.children = children
        self.infants_in_seat = infants_in_seat
        self.infants_on_lap = infants_on_lap

    def pb(self) -> list[Passenger]:
        return [
            *(Passenger.ADULT for _ in range(self.adults)),
            *(Passenger.CHILD for _ in range(self.children)),
            *(Passenger.INFANT_IN_SEAT for _ in range(self.infants_in_seat)),
            *(Passenger.INFANT_ON_LAP for _ in range(self.infants_on_lap)),
        ]


DEFAULT_PASSENGERS = Passengers(adults=1)
SEAT_LOOKUP = {
    "economy": Seat.ECONOMY,
    "premium-economy": Seat.PREMIUM_ECONOMY,
    "business": Seat.BUSINESS,
    "first": Seat.FIRST,
}
TRIP_LOOKUP = {
    "round-trip": Trip.ROUND_TRIP,
    "one-way": Trip.ONE_WAY,
    "multi-city": Trip.MULTI_CITY,
}


def create_query(
    *,
    flights: list[FlightQuery],
    seat: SeatType = "economy",
    trip: TripType = "one-way",
    passengers: Passengers = DEFAULT_PASSENGERS,
    language: str | Literal[""] | Language = "",
    currency: str | Literal[""] | Currency = "",
    max_stops: int | None = None,
    tfu: str | None = None,
    selected_outbound_airline_code: str | None = None,
    selected_outbound_flight_number: str | None = None,
) -> Query:
    """Create a query.

    Args:
        flights: The flight queries.
        seat: Desired seat type.
        trip: Trip type.
        passengers: Passengers.
        language: Set the language. Use `""` (blank str) to let Google decide.
        currency: Set the currency. Use `""` (blank str) to let Google decide.
        max_stops (optional): Set the maximum stops for every flight query, if present.
        tfu (optional): Search token from a prior round-trip call for second-step lookup.
        selected_outbound_airline_code (optional): Airline code of selected outbound.
        selected_outbound_flight_number (optional): Flight number of selected outbound.
    """
    selected_outbound = None
    if (
        tfu
        and trip == "round-trip"
        and flights
        and selected_outbound_airline_code
        and selected_outbound_flight_number
    ):
        first_flight = flights[0]
        if isinstance(first_flight.date, str):
            first_date = first_flight.date
        else:
            first_date = first_flight.date.strftime("%Y-%m-%d")
        selected_outbound = SelectedOutbound(
            from_airport=first_flight.from_airport,
            date=first_date,
            to_airport=first_flight.to_airport,
            airline_code=selected_outbound_airline_code,
            flight_number=selected_outbound_flight_number,
        )

    return Query(
        flight_data=[flight._setmaxstops(max_stops).pb() for flight in flights],
        seat=SEAT_LOOKUP[seat],
        trip=TRIP_LOOKUP[trip],
        passengers=passengers.pb(),
        language=language,
        currency=currency,
        tfu=tfu,
        selected_outbound=selected_outbound,
    )
