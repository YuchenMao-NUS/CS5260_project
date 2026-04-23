"""Adapters between MCP-facing payloads and flights_search domain models."""

from __future__ import annotations

import base64
import json

from flights_search.models import (
    ContinuationHandle,
    FlightOption,
    FlightSearchRequest,
    Passengers,
    SearchResults,
    SelectedItinerary,
    SelectedLeg,
    SelectedSegment,
    TripLeg,
)

from .errors import UnsupportedUsageError, ValidationError
from .schemas import (
    FlightSegmentOutput,
    PassengersInput,
    ResolveBookingUrlsResponse,
    SearchFlightOptionOutput,
    SearchFlightsResponse,
    SelectedItineraryModel,
    SelectedLegModel,
    SelectedSegmentModel,
    TripLegInput,
)

_HANDLE_VERSION = 1
_MISSING_SEGMENT_IDENTITY = "missing_segment_identity"
_MISSING_CONTINUATION_TOKEN = "missing_continuation_token"


def build_search_request(
    *,
    legs: list[TripLegInput],
    trip_type: str,
    passengers: PassengersInput | None,
    seat: str,
    language: str,
    currency: str,
) -> FlightSearchRequest:
    """Convert an MCP request payload into a validated domain request."""

    normalized_passengers = passengers or PassengersInput()
    try:
        return FlightSearchRequest(
            legs=tuple(
                TripLeg(
                    date=leg.date,
                    origin_airport=leg.origin_airport,
                    destination_airport=leg.destination_airport,
                    max_stops=leg.max_stops,
                    airline_codes=tuple(leg.airline_codes),
                )
                for leg in legs
            ),
            passengers=Passengers(
                adults=normalized_passengers.adults,
                children=normalized_passengers.children,
                infants_in_seat=normalized_passengers.infants_in_seat,
                infants_on_lap=normalized_passengers.infants_on_lap,
            ),
            seat=seat,
            trip_type=trip_type,
            language=language,
            currency=currency,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def adapt_search_results(
    results: SearchResults,
    request: FlightSearchRequest,
    *,
    selected_outbound_leg: SelectedLeg | None = None,
) -> SearchFlightsResponse:
    """Convert typed domain search results into MCP-friendly JSON models."""

    options: list[SearchFlightOptionOutput] = []
    for option in results.options:
        request_leg_date = _get_request_leg_date(
            request=request,
            results=results,
            selected_outbound_leg=selected_outbound_leg,
        )
        selected_leg, selection_reason = _build_selected_leg(
            option,
            request_leg_date=request_leg_date,
        )
        outbound_selection_handle: str | None = None
        selected_itinerary: SelectedItinerary | None = None
        if request.trip_type == "round-trip":
            if results.selection_phase == "initial":
                if selected_leg is None:
                    outbound_selection_handle = None
                elif option.continuation is None or option.continuation.is_empty():
                    selection_reason = _MISSING_CONTINUATION_TOKEN
                else:
                    outbound_selection_handle = encode_outbound_selection_handle(
                        continuation=option.continuation,
                        selected_leg=selected_leg,
                    )
            else:
                if selected_outbound_leg is None:
                    raise ValidationError(
                        "Follow-up result adaptation requires the selected outbound leg."
                    )
                if selected_leg is None:
                    selected_itinerary = None
                else:
                    selected_itinerary = SelectedItinerary(
                        legs=(selected_outbound_leg, selected_leg)
                    )

        options.append(
            SearchFlightOptionOutput(
                kind=option.kind,
                price=option.price,
                airlines=list(option.airlines),
                segment_count=len(option.segments),
                stop_count=max(0, len(option.segments) - 1),
                segments=[
                    FlightSegmentOutput(
                        origin_airport=segment.origin.code,
                        origin_airport_name=segment.origin.name,
                        destination_airport=segment.destination.code,
                        destination_airport_name=segment.destination.name,
                        date=request_leg_date,
                        departure_time=segment.departure_time,
                        arrival_time=segment.arrival_time,
                        duration_minutes=segment.duration_minutes,
                        marketing_airline_code=segment.marketing_airline_code,
                        flight_number=segment.flight_number,
                        aircraft_type=segment.aircraft_type,
                    )
                    for segment in option.segments
                ],
                selected_leg=(
                    selected_leg_to_model(selected_leg) if selected_leg is not None else None
                ),
                selected_itinerary=(
                    selected_itinerary_to_model(selected_itinerary)
                    if selected_itinerary is not None
                    else None
                ),
                outbound_selection_handle=outbound_selection_handle,
                selection_unavailable_reason=selection_reason,
            )
        )

    return SearchFlightsResponse(
        selection_phase=results.selection_phase,
        options=options,
    )


def encode_outbound_selection_handle(
    *,
    continuation: ContinuationHandle,
    selected_leg: SelectedLeg,
) -> str:
    """Encode round-trip follow-up state into an opaque transport token."""

    payload = {
        "version": _HANDLE_VERSION,
        "continuation_token": continuation._value,
        "selected_leg": selected_leg_to_model(selected_leg).model_dump(mode="json"),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_outbound_selection_handle(handle: str) -> tuple[ContinuationHandle, SelectedLeg]:
    """Decode an outbound-selection handle back into domain follow-up inputs."""

    if not handle:
        raise ValidationError("Outbound selection handle must not be empty.")
    try:
        decoded = base64.urlsafe_b64decode(handle.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("Outbound selection handle is not valid base64 JSON.") from exc

    if payload.get("version") != _HANDLE_VERSION:
        raise ValidationError("Outbound selection handle version is not supported.")

    continuation_token = payload.get("continuation_token")
    if not isinstance(continuation_token, str) or continuation_token == "":
        raise ValidationError(
            "Outbound selection handle is missing a continuation token."
        )

    selected_leg_payload = payload.get("selected_leg")
    if not isinstance(selected_leg_payload, dict):
        raise ValidationError("Outbound selection handle is missing selected-leg data.")

    try:
        selected_leg_model = SelectedLegModel.model_validate(selected_leg_payload)
    except Exception as exc:
        raise ValidationError(
            "Outbound selection handle contains invalid selected-leg data."
        ) from exc

    return (
        ContinuationHandle(continuation_token),
        model_to_selected_leg(selected_leg_model),
    )


def selected_leg_to_model(selected_leg: SelectedLeg) -> SelectedLegModel:
    return SelectedLegModel(
        segments=[
            SelectedSegmentModel(
                origin_airport=segment.origin_airport,
                date=segment.date,
                destination_airport=segment.destination_airport,
                marketing_airline_code=segment.marketing_airline_code,
                flight_number=segment.flight_number,
            )
            for segment in selected_leg.segments
        ]
    )


def selected_itinerary_to_model(
    selected_itinerary: SelectedItinerary,
) -> SelectedItineraryModel:
    return SelectedItineraryModel(
        legs=[
            selected_leg_to_model(selected_leg)
            for selected_leg in selected_itinerary.legs
        ]
    )


def model_to_selected_leg(selected_leg: SelectedLegModel) -> SelectedLeg:
    try:
        return SelectedLeg(
            segments=tuple(
                SelectedSegment(
                    origin_airport=segment.origin_airport,
                    date=segment.date,
                    destination_airport=segment.destination_airport,
                    marketing_airline_code=segment.marketing_airline_code,
                    flight_number=segment.flight_number,
                )
                for segment in selected_leg.segments
            )
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def model_to_selected_itinerary(
    selected_itinerary: SelectedItineraryModel,
) -> SelectedItinerary:
    try:
        return SelectedItinerary(
            legs=tuple(
                model_to_selected_leg(selected_leg)
                for selected_leg in selected_itinerary.legs
            )
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def validate_follow_up_request(
    request: FlightSearchRequest,
    outbound_selection_handle: str,
) -> tuple[ContinuationHandle, SelectedLeg]:
    """Validate follow-up MCP inputs before calling the domain API."""

    if request.trip_type != "round-trip":
        raise UnsupportedUsageError(
            "search_return_flights requires trip_type='round-trip'."
        )
    if len(request.legs) != 2:
        raise ValidationError(
            "search_return_flights requires exactly two trip legs."
        )

    continuation, selected_leg = decode_outbound_selection_handle(
        outbound_selection_handle
    )
    _validate_selected_leg_matches_search_leg(selected_leg, request.legs[0])
    return continuation, selected_leg


def validate_booking_request(
    request: FlightSearchRequest,
    itinerary: SelectedItineraryModel,
) -> SelectedItinerary:
    """Validate booking MCP inputs before calling the domain booking API."""

    selected_itinerary = model_to_selected_itinerary(itinerary)
    if len(selected_itinerary.legs) != len(request.legs):
        raise ValidationError(
            "Selected itinerary leg count must match the original search request."
        )

    for search_leg, selected_leg in zip(
        request.legs,
        selected_itinerary.legs,
        strict=True,
    ):
        first_segment = selected_leg.segments[0]
        last_segment = selected_leg.segments[-1]
        if first_segment.origin_airport != search_leg.origin_airport:
            raise ValidationError(
                "Selected itinerary origin must match the original search leg."
            )
        if first_segment.date != search_leg.date:
            raise ValidationError(
                "Selected itinerary departure date must match the original search leg."
            )
        if last_segment.destination_airport != search_leg.destination_airport:
            raise ValidationError(
                "Selected itinerary destination must match the original search leg."
            )

    return selected_itinerary


def adapt_booking_urls(urls: list[str]) -> ResolveBookingUrlsResponse:
    """Convert resolved booking URL candidates into the MCP response shape."""

    return ResolveBookingUrlsResponse(booking_urls=urls)


def _build_selected_leg(
    option: FlightOption,
    *,
    request_leg_date: str,
) -> tuple[SelectedLeg | None, str | None]:
    selected_segments: list[SelectedSegment] = []
    for segment in option.segments:
        if not segment.marketing_airline_code or not segment.flight_number:
            return None, _MISSING_SEGMENT_IDENTITY
        selected_segments.append(
            SelectedSegment(
                origin_airport=segment.origin.code,
                date=request_leg_date,
                destination_airport=segment.destination.code,
                marketing_airline_code=segment.marketing_airline_code,
                flight_number=segment.flight_number,
            )
        )
    return SelectedLeg(segments=tuple(selected_segments)), None


def _get_request_leg_date(
    *,
    request: FlightSearchRequest,
    results: SearchResults,
    selected_outbound_leg: SelectedLeg | None,
) -> str:
    if results.selection_phase == "follow-up":
        if len(request.legs) < 2:
            raise ValidationError(
                "Follow-up results require a round-trip request with two legs."
            )
        if selected_outbound_leg is None:
            raise ValidationError(
                "Follow-up results require the selected outbound leg."
            )
        return request.legs[1].date
    return request.legs[0].date


def _validate_selected_leg_matches_search_leg(
    selected_leg: SelectedLeg,
    search_leg: TripLeg,
) -> None:
    first_segment = selected_leg.segments[0]
    last_segment = selected_leg.segments[-1]
    if first_segment.origin_airport != search_leg.origin_airport:
        raise ValidationError(
            "Outbound selection handle origin does not match the first search leg."
        )
    if first_segment.date != search_leg.date:
        raise ValidationError(
            "Outbound selection handle date does not match the first search leg."
        )
    if last_segment.destination_airport != search_leg.destination_airport:
        raise ValidationError(
            "Outbound selection handle destination does not match the first search leg."
        )
