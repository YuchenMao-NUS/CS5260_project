"""MCP tool registration for flights_search."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import anyio
from mcp.server.fastmcp import FastMCP

from flights_search import (
    build_booking_request as domain_build_booking_request,
    get_booking_urls as domain_get_booking_urls,
    search_flights as domain_search_flights,
    search_follow_up_flights as domain_search_follow_up_flights,
)

from .adapters import (
    adapt_booking_urls,
    adapt_search_results,
    build_search_request,
    validate_booking_request,
    validate_follow_up_request,
)
from .errors import (
    UnsupportedUsageError,
    ValidationError,
    raise_mapped_runtime_error,
    raise_unsupported_usage,
    raise_validation_error,
)
from .schemas import (
    PassengersInput,
    ResolveBookingUrlsResponse,
    SearchFlightsResponse,
    SelectedItineraryModel,
    SeatType,
    ServerInfoResponse,
    TripLegInput,
    TripType,
)

EXPOSED_TOOLS = [
    "server_info",
    "search_flights",
    "search_return_flights",
    "resolve_booking_urls",
]
DEFAULT_SERVER_VERSION = "0.1.0"


def register_tools(server: FastMCP) -> None:
    @server.tool(
        name="server_info",
        description="Return MCP server metadata and currently exposed capabilities.",
    )
    def server_info() -> ServerInfoResponse:
        return ServerInfoResponse(
            server_name="flights-search-mcp",
            version=_package_version(),
            transport="stdio",
            tools=EXPOSED_TOOLS,
        )

    @server.tool(
        name="search_flights",
        description="Execute an initial Google Flights search from a structured request.",
    )
    def search_flights(
        legs: list[TripLegInput],
        trip_type: TripType = "one-way",
        passengers: PassengersInput | None = None,
        seat: SeatType = "economy",
        language: str = "en-US",
        currency: str = "USD",
    ) -> SearchFlightsResponse:
        try:
            request = build_search_request(
                legs=legs,
                trip_type=trip_type,
                passengers=passengers,
                seat=seat,
                language=language,
                currency=currency,
            )
            results = domain_search_flights(request)
            return adapt_search_results(results, request)
        except ValidationError as exc:
            raise_validation_error(str(exc))
        except UnsupportedUsageError as exc:
            raise_unsupported_usage(str(exc))
        except Exception as exc:
            raise_mapped_runtime_error(exc)

    @server.tool(
        name="search_return_flights",
        description=(
            "Execute the round-trip return-options follow-up using an outbound "
            "selection handle returned by search_flights."
        ),
    )
    def search_return_flights(
        outbound_selection_handle: str,
        legs: list[TripLegInput],
        trip_type: TripType = "round-trip",
        passengers: PassengersInput | None = None,
        seat: SeatType = "economy",
        language: str = "en-US",
        currency: str = "USD",
    ) -> SearchFlightsResponse:
        try:
            request = build_search_request(
                legs=legs,
                trip_type=trip_type,
                passengers=passengers,
                seat=seat,
                language=language,
                currency=currency,
            )
            continuation, selected_outbound_leg = validate_follow_up_request(
                request,
                outbound_selection_handle,
            )
            results = domain_search_follow_up_flights(
                request,
                continuation=continuation,
                selected_outbound_leg=selected_outbound_leg,
            )
            return adapt_search_results(
                results,
                request,
                selected_outbound_leg=selected_outbound_leg,
            )
        except ValidationError as exc:
            raise_validation_error(str(exc))
        except UnsupportedUsageError as exc:
            raise_unsupported_usage(str(exc))
        except Exception as exc:
            raise_mapped_runtime_error(exc)

    @server.tool(
        name="resolve_booking_urls",
        description=(
            "Resolve booking URL candidates for an explicit selected itinerary "
            "that matches the original search request."
        ),
    )
    async def resolve_booking_urls(
        itinerary: SelectedItineraryModel,
        legs: list[TripLegInput],
        trip_type: TripType = "one-way",
        passengers: PassengersInput | None = None,
        seat: SeatType = "economy",
        language: str = "en-US",
        currency: str = "USD",
    ) -> ResolveBookingUrlsResponse:
        try:
            request = build_search_request(
                legs=legs,
                trip_type=trip_type,
                passengers=passengers,
                seat=seat,
                language=language,
                currency=currency,
            )
            selected_itinerary = validate_booking_request(request, itinerary)
            urls = await anyio.to_thread.run_sync(
                _resolve_booking_urls_sync,
                request,
                selected_itinerary,
            )
            return adapt_booking_urls(urls)
        except ValidationError as exc:
            raise_validation_error(str(exc))
        except UnsupportedUsageError as exc:
            raise_unsupported_usage(str(exc))
        except Exception as exc:
            raise_mapped_runtime_error(exc)


def _package_version() -> str:
    try:
        return version("flights-search")
    except PackageNotFoundError:
        return DEFAULT_SERVER_VERSION


def _resolve_booking_urls_sync(request, selected_itinerary) -> list[str]:
    booking_request = domain_build_booking_request(request, selected_itinerary)
    return domain_get_booking_urls(booking_request)
