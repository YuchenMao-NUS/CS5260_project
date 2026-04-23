"""Google Flights booking-link resolution helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .browser import fetch_booking_result_texts

BOOKING_LINK_BASE = "https://www.google.com/travel/clk/f"
BOOKING_LINK_PATTERN = re.compile(
    r"https?://www\.google\.com/travel/clk/f\?u=([A-Za-z0-9._~%-]+)"
)


def resolve_booking_urls(params: dict[str, str]) -> list[str]:
    """Capture and extract candidate booking URLs for the provided params.

    Return an empty list only when the booking lookup succeeds but the captured
    payloads do not expose extractable links.
    """

    texts = fetch_booking_result_texts(params)
    if not texts:
        return []

    links: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for link in extract_booking_urls(text):
            if link not in seen:
                seen.add(link)
                links.append(link)
    return links


def extract_booking_urls(text: str) -> list[str]:
    """Extract Google Flights outbound booking URLs from raw response text."""

    links: list[str] = []
    seen: set[str] = set()

    for link in _extract_structured_booking_urls(text):
        if link not in seen:
            seen.add(link)
            links.append(link)

    for token in BOOKING_LINK_PATTERN.findall(text):
        link = _build_booking_link(token)
        if link not in seen:
            seen.add(link)
            links.append(link)

    return links


def _extract_structured_booking_urls(text: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for root in _iter_response_roots(text):
        for value in _iter_nested_values(root):
            if not (
                isinstance(value, list)
                and len(value) >= 2
                and value[0] == BOOKING_LINK_BASE
                and isinstance(value[1], list)
            ):
                continue

            token = _extract_u_param_from_pairs(value[1])
            if token is None:
                continue

            link = _build_booking_link(token)
            if link not in seen:
                seen.add(link)
                links.append(link)

    return links


def _iter_response_roots(value: Any) -> Iterable[Any]:
    decoded = _maybe_parse_json_string(value)
    if decoded is not None:
        yield decoded
        return

    if not isinstance(value, str):
        return

    stripped = value.lstrip()
    if stripped.startswith(")]}'"):
        _, _, stripped = stripped.partition("\n")

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.isdigit() and index + 1 < len(lines):
            decoded = _maybe_parse_json_string(lines[index + 1])
            if decoded is not None:
                yield decoded
                index += 2
                continue

        decoded = _maybe_parse_json_string(line)
        if decoded is not None:
            yield decoded
        index += 1


def _maybe_parse_json_string(value: Any) -> Any | None:
    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _iter_nested_values(value: Any) -> Iterable[Any]:
    roots = list(_iter_response_roots(value))
    if roots:
        for root in roots:
            yield from _iter_nested_values(root)
        return

    yield value
    if isinstance(value, list):
        for item in value:
            yield from _iter_nested_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_nested_values(item)


def _extract_u_param_from_pairs(value: list[Any]) -> str | None:
    for item in value:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and item[0] == "u"
            and isinstance(item[1], str)
        ):
            return item[1]
    return None


def _build_booking_link(token: str) -> str:
    return f"{BOOKING_LINK_BASE}?u={token}"
