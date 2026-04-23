"""Request encoding primitives for Google Flights transport params."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass

from flights_search.models import (
    BookingRequest,
    ContinuationHandle,
    FlightSearchRequest,
    SelectedLeg,
    SelectedSegment,
    TripLeg,
)

SEAT_LOOKUP = {
    "economy": 1,
    "premium-economy": 2,
    "business": 3,
    "first": 4,
}

TRIP_LOOKUP = {
    "round-trip": 1,
    "one-way": 2,
    "multi-city": 3,
}

PASSENGER_LOOKUP = {
    "adults": 1,
    "children": 2,
    "infants_in_seat": 3,
    "infants_on_lap": 4,
}


@dataclass(frozen=True)
class EncodedRequest:
    params: dict[str, str]


def encode_search_request(request: FlightSearchRequest) -> EncodedRequest:
    """Encode an initial search request into Google Flights params."""

    return EncodedRequest(
        params={
            "tfs": _encode_tfs(request),
            "hl": request.language,
            "curr": request.currency,
        }
    )


def encode_follow_up_request(
    request: FlightSearchRequest,
    *,
    continuation: ContinuationHandle,
    selected_outbound_leg: SelectedLeg,
) -> EncodedRequest:
    """Encode a follow-up request after the user selects the outbound leg."""

    if continuation.is_empty():
        raise ValueError("Follow-up requests require a non-empty continuation token.")

    return EncodedRequest(
        params={
            "tfs": _encode_tfs(request, selections={0: selected_outbound_leg.segments}),
            "hl": request.language,
            "curr": request.currency,
            "tfu": continuation._value,
        }
    )


def encode_booking_request(request: BookingRequest) -> EncodedRequest:
    """Encode the final booking request transport params.

    Booking params intentionally omit the continuation token from the final
    request surface, matching the legacy Google Flights booking URL behavior.
    """

    selections = {
        index: leg.segments for index, leg in enumerate(request.itinerary.legs)
    }
    return EncodedRequest(
        params={
            "tfs": _encode_tfs(request.search_request, selections=selections),
            "hl": request.search_request.language,
            "curr": request.search_request.currency,
        }
    )


def _encode_tfs(
    request: FlightSearchRequest,
    *,
    selections: dict[int, tuple[SelectedSegment, ...]] | None = None,
) -> str:
    payload = _encode_info_message(request)
    if selections:
        payload = _inject_selected_segments(payload, selections)
    return b64encode(payload).decode("utf-8")


def _encode_info_message(request: FlightSearchRequest) -> bytes:
    chunks: list[bytes] = []
    for leg in request.legs:
        chunks.append(_wire_message(3, _encode_trip_leg(leg)))

    for field_name, enum_value in PASSENGER_LOOKUP.items():
        count = getattr(request.passengers, field_name)
        chunks.extend(_wire_varint(8, enum_value) for _ in range(count))

    chunks.append(_wire_varint(9, SEAT_LOOKUP[request.seat]))
    chunks.append(_wire_varint(19, TRIP_LOOKUP[request.trip_type]))
    return b"".join(chunks)


def _encode_trip_leg(leg: TripLeg) -> bytes:
    chunks = [
        _wire_str(2, leg.date),
        _wire_message(13, _wire_str(2, leg.origin_airport)),
        _wire_message(14, _wire_str(2, leg.destination_airport)),
    ]
    if leg.max_stops is not None:
        chunks.append(_wire_varint(5, leg.max_stops))
    chunks.extend(_wire_str(6, code) for code in leg.airline_codes)
    return b"".join(chunks)


def _inject_selected_segments(
    info_bytes: bytes, selections: dict[int, tuple[SelectedSegment, ...]]
) -> bytes:
    index = 0
    offset = 0
    out = bytearray()

    while offset < len(info_bytes):
        tag_start = offset
        tag, offset = _decode_varint(info_bytes, offset)
        field_no = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:
            _, offset = _decode_varint(info_bytes, offset)
            out.extend(info_bytes[tag_start:offset])
            continue

        if wire_type != 2:
            out.extend(info_bytes[tag_start:])
            break

        length, after_length = _decode_varint(info_bytes, offset)
        value_start = after_length
        value_end = value_start + length
        if value_end > len(info_bytes):
            out.extend(info_bytes[tag_start:])
            break

        if field_no == 3:
            flight_data = info_bytes[value_start:value_end]
            for segment in selections.get(index, ()):
                flight_data += _wire_message(4, _encode_selected_segment(segment))
            out.extend(_encode_varint(tag))
            out.extend(_encode_varint(len(flight_data)))
            out.extend(flight_data)
            index += 1
        else:
            out.extend(info_bytes[tag_start:value_end])
        offset = value_end

    return bytes(out)


def _encode_selected_segment(segment: SelectedSegment) -> bytes:
    return b"".join(
        [
            _wire_str(1, segment.origin_airport),
            _wire_str(2, segment.date),
            _wire_str(3, segment.destination_airport),
            _wire_str(5, segment.marketing_airline_code),
            _wire_str(6, segment.flight_number),
        ]
    )


def _wire_varint(field_no: int, value: int) -> bytes:
    return _encode_varint((field_no << 3) | 0) + _encode_varint(value)


def _wire_str(field_no: int, value: str) -> bytes:
    payload = value.encode("utf-8")
    return _wire_message(field_no, payload)


def _wire_message(field_no: int, payload: bytes) -> bytes:
    return _encode_varint((field_no << 3) | 2) + _encode_varint(len(payload)) + payload


def _encode_varint(value: int) -> bytes:
    out = bytearray()
    current = value
    while True:
        chunk = current & 0x7F
        current >>= 7
        if current:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            break
    return bytes(out)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    shift = 0
    result = 0
    index = offset
    while index < len(data):
        byte = data[index]
        result |= (byte & 0x7F) << shift
        index += 1
        if byte & 0x80 == 0:
            return result, index
        shift += 7
    raise ValueError("Incomplete varint.")
