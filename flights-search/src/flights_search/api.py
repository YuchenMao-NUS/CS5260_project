"""Top-level API surface for the greenfield package."""

from __future__ import annotations

from .booking import resolve_booking_urls
from .client import fetch_search_html
from .encoder import (
    encode_booking_request,
    encode_follow_up_request,
    encode_search_request,
)
from .models import (
    BookingRequest,
    ContinuationHandle,
    FlightSearchRequest,
    SearchResults,
    SelectedItinerary,
    SelectedLeg,
)
from .parser import parse_search_html


def search_flights(request: FlightSearchRequest) -> SearchResults:
    """Search Google Flights for the provided request.
    """
    encoded = encode_search_request(request)
    html = fetch_search_html(encoded.params)
    return parse_search_html(html)


def search_follow_up_flights(
    request: FlightSearchRequest,
    *,
    continuation: ContinuationHandle,
    selected_outbound_leg: SelectedLeg,
) -> SearchResults:
    """Request round-trip return options after selecting an outbound leg."""

    encoded = encode_follow_up_request(
        request,
        continuation=continuation,
        selected_outbound_leg=selected_outbound_leg,
    )
    html = fetch_search_html(encoded.params)
    parsed = parse_search_html(html)
    return SearchResults(options=parsed.options, selection_phase="follow-up")


def build_booking_request(
    request: FlightSearchRequest, itinerary: SelectedItinerary
) -> BookingRequest:
    """Build a typed booking request from an explicit selected itinerary."""

    return BookingRequest(search_request=request, itinerary=itinerary)


def get_booking_urls(request: BookingRequest) -> list[str]:
    """Resolve booking URL candidates for a selected itinerary."""

    encoded = encode_booking_request(request)
    return resolve_booking_urls(encoded.params)


def get_booking_url(request: BookingRequest) -> str | None:
    """Convenience wrapper that returns the first booking URL, if any."""

    urls = get_booking_urls(request)
    return urls[0] if urls else None
