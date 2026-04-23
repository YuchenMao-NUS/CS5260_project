"""Thin MCP client for the local flights-search stdio server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import os
from time import perf_counter
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from smartflight.config import settings

DEFAULT_TOOL_TIMEOUT_SECONDS = 60
logger = logging.getLogger(__name__)


@dataclass
class FlightsMcpError(Exception):
    message: str
    code: str = "mcp_runtime_error"
    retryable: bool = False
    remediation: str | None = None

    def __str__(self) -> str:
        return self.message


def _server_environment() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(settings.FLIGHTS_SEARCH_SRC)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing else os.pathsep.join([src_path, existing])
    )
    return env


def _server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=settings.FLIGHTS_SEARCH_SERVER_PYTHON,
        args=["-m", settings.FLIGHTS_SEARCH_SERVER_MODULE],
        env=_server_environment(),
        cwd=settings.FLIGHTS_SEARCH_REPO,
    )


def _ensure_server_repo_exists() -> None:
    if not settings.FLIGHTS_SEARCH_REPO.exists():
        raise FlightsMcpError(
            message=(
                "Flights MCP server repository was not found at "
                f"{settings.FLIGHTS_SEARCH_REPO}."
            ),
            code="mcp_server_missing",
            remediation="Restore flights-search or update FLIGHTS_SEARCH_REPO.",
        )
    if not settings.FLIGHTS_SEARCH_SRC.exists():
        raise FlightsMcpError(
            message=(
                "Flights MCP server source directory was not found at "
                f"{settings.FLIGHTS_SEARCH_SRC}."
            ),
            code="mcp_server_missing",
            remediation="Restore flights-search/src or update FLIGHTS_SEARCH_REPO.",
        )


def _extract_tool_payload(result) -> dict[str, Any]:
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    if getattr(result, "content", None):
        for item in result.content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip().startswith("{"):
                import json

                return json.loads(text)
    return {}


def _raise_tool_error(result) -> None:
    payload = _extract_tool_payload(result)
    message = payload.get("message") or "Flights MCP tool call failed."
    raise FlightsMcpError(
        message=message,
        code=payload.get("code") or "mcp_tool_error",
        retryable=bool(payload.get("retryable")),
        remediation=payload.get("remediation"),
    )


async def _call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    _ensure_server_repo_exists()
    server = _server_parameters()

    try:
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=timeout_seconds),
                )
    except FlightsMcpError:
        raise
    except Exception as exc:
        raise FlightsMcpError(
            message=f"Flights MCP server call failed for {name}: {exc}",
            code="mcp_runtime_error",
        ) from exc

    if getattr(result, "isError", False):
        _raise_tool_error(result)

    return _extract_tool_payload(result)


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    started_at = perf_counter()
    async def runner() -> dict[str, Any]:
        return await _call_tool(
            name,
            arguments,
            timeout_seconds=timeout_seconds,
        )

    try:
        payload = anyio.run(runner)
    except Exception:
        logger.warning(
            "MCP tool call failed",
            extra={
                "provider": "mcp",
                "operation": name,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
            },
            exc_info=True,
        )
        raise

    logger.info(
        "MCP tool call completed",
        extra={
            "provider": "mcp",
            "operation": name,
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
        },
    )
    return payload


def search_flights(
    *,
    legs: list[dict[str, Any]],
    trip_type: str,
    passengers: dict[str, int] | None,
    seat: str,
    language: str,
    currency: str,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return call_tool(
        "search_flights",
        {
            "legs": legs,
            "trip_type": trip_type,
            "passengers": passengers,
            "seat": seat,
            "language": language,
            "currency": currency,
        },
        timeout_seconds=timeout_seconds,
    )


def search_return_flights(
    *,
    outbound_selection_handle: str,
    legs: list[dict[str, Any]],
    trip_type: str,
    passengers: dict[str, int] | None,
    seat: str,
    language: str,
    currency: str,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return call_tool(
        "search_return_flights",
        {
            "outbound_selection_handle": outbound_selection_handle,
            "legs": legs,
            "trip_type": trip_type,
            "passengers": passengers,
            "seat": seat,
            "language": language,
            "currency": currency,
        },
        timeout_seconds=timeout_seconds,
    )


def resolve_booking_urls(
    *,
    itinerary: dict[str, Any],
    legs: list[dict[str, Any]],
    trip_type: str,
    passengers: dict[str, int] | None,
    seat: str,
    language: str,
    currency: str,
    timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> list[str]:
    payload = call_tool(
        "resolve_booking_urls",
        {
            "itinerary": itinerary,
            "legs": legs,
            "trip_type": trip_type,
            "passengers": passengers,
            "seat": seat,
            "language": language,
            "currency": currency,
        },
        timeout_seconds=timeout_seconds,
    )
    return list(payload.get("booking_urls") or [])
