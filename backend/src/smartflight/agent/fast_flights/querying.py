from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime as Datetime
from urllib.parse import urlencode
from typing import Literal

from .pb.flights_pb2 import Airport, FlightData, Info, Passenger, Seat, Trip
from .types import Currency, Language, SeatType, TripType


@dataclass
class SelectedFlight:
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


def _encode_selected_flight_field(s: SelectedFlight) -> bytes:
    payload = b"".join(
        [
            _wire_str(1, s.from_airport),
            _wire_str(2, s.date),
            _wire_str(3, s.to_airport),
            _wire_str(5, s.airline_code),
            _wire_str(6, s.flight_number),
        ]
    )
    return bytes([(4 << 3) | 2]) + _encode_varint(len(payload)) + payload


def _inject_selected_flights(
    info_bytes: bytes, selected_by_leg: dict[int, list[SelectedFlight]]
) -> bytes:
    i = 0
    out = bytearray()
    flight_data_index = 0

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

        selected_segments = (
            selected_by_leg.get(flight_data_index, []) if field_no == 3 else []
        )
        if field_no == 3:
            original_flight_data = info_bytes[value_start:value_end]
            for selected in selected_segments:
                original_flight_data += _encode_selected_flight_field(selected)
            out.extend(_encode_varint(tag))
            out.extend(_encode_varint(len(original_flight_data)))
            out.extend(original_flight_data)
            flight_data_index += 1
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
    selected_flight: list[SelectedFlight] | None = None
    selected_outbound_flight: list[SelectedFlight] | None = None
    selected_return_flight: list[SelectedFlight] | None = None

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
        selected_by_leg: dict[int, list[SelectedFlight]] = {}
        if self.selected_flight is not None:
            selected_by_leg[0] = self.selected_flight
        if self.selected_outbound_flight is not None:
            selected_by_leg[0] = self.selected_outbound_flight
        if self.selected_return_flight is not None:
            selected_by_leg[1] = self.selected_return_flight
        if selected_by_leg:
            return _inject_selected_flights(data, selected_by_leg)
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

    def booking_url(self) -> str:
        """Get the Google Flights booking page URL for this query."""
        return "https://www.google.com/travel/flights/booking?" + urlencode(
            self.booking_params()
        )

    def params(self) -> dict[str, str]:
        """Create `params` in dictionary form."""
        params = {"tfs": self.to_str(), "hl": self.language, "curr": self.currency}
        if self.tfu:
            params["tfu"] = self.tfu
        return params

    def booking_params(self) -> dict[str, str]:
        """Create params for the booking page."""
        return {"tfs": self.to_str(), "hl": self.language, "curr": self.currency}

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
    selected_flight_airline_code: str | None = None,
    selected_flight_number: str | None = None,
    selected_flight_segments: list[SelectedFlight] | None = None,
    selected_outbound_airline_code: str | None = None,
    selected_outbound_flight_number: str | None = None,
    selected_outbound_segments: list[SelectedFlight] | None = None,
    selected_return_airline_code: str | None = None,
    selected_return_flight_number: str | None = None,
    selected_return_segments: list[SelectedFlight] | None = None,
) -> Query:
    """Create a query."""

    def _build_selected_flight(
        flight_query: FlightQuery,
        *,
        airline_code: str | None,
        flight_number: str | None,
    ) -> SelectedFlight | None:
        if not airline_code or not flight_number:
            return None
        if isinstance(flight_query.date, str):
            flight_date = flight_query.date
        else:
            flight_date = flight_query.date.strftime("%Y-%m-%d")
        return SelectedFlight(
            from_airport=flight_query.from_airport,
            date=flight_date,
            to_airport=flight_query.to_airport,
            airline_code=airline_code,
            flight_number=flight_number,
        )

    def _build_selected_flights(
        flight_query: FlightQuery | None,
        *,
        segments: list[SelectedFlight] | None,
        airline_code: str | None,
        flight_number: str | None,
    ) -> list[SelectedFlight] | None:
        if segments:
            return segments
        if flight_query is None:
            return None
        selected = _build_selected_flight(
            flight_query,
            airline_code=airline_code,
            flight_number=flight_number,
        )
        return [selected] if selected is not None else None

    selected_flight = _build_selected_flights(
        flights[0] if flights else None,
        segments=selected_flight_segments,
        airline_code=selected_flight_airline_code,
        flight_number=selected_flight_number,
    )

    selected_outbound_flight = _build_selected_flights(
        flights[0] if flights else None,
        segments=selected_outbound_segments,
        airline_code=selected_outbound_airline_code,
        flight_number=selected_outbound_flight_number,
    )

    selected_return_flight = _build_selected_flights(
        flights[1] if len(flights) > 1 else None,
        segments=selected_return_segments,
        airline_code=selected_return_airline_code,
        flight_number=selected_return_flight_number,
    )

    return Query(
        flight_data=[flight._setmaxstops(max_stops).pb() for flight in flights],
        seat=SEAT_LOOKUP[seat],
        trip=TRIP_LOOKUP[trip],
        passengers=passengers.pb(),
        language=language,
        currency=currency,
        tfu=tfu,
        selected_flight=selected_flight,
        selected_outbound_flight=selected_outbound_flight,
        selected_return_flight=selected_return_flight,
    )
