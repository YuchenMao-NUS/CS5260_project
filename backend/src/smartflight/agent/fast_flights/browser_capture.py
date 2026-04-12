from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import BrowserContext, Page, Response, async_playwright

from .querying import Query

logger = logging.getLogger(__name__)

BOOKING_RESULTS_URL_PART = (
    "/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/"
    "GetBookingResults"
)
DEFAULT_OUTPUT_DIR = Path("captures") / "booking_results"
BOOKING_LINK_BASE = "https://www.google.com/travel/clk/f"
BOOKING_LINK_PATTERN = re.compile(
    r'https://www\.google\.com/travel/clk/f\\?",\[\[\\?"u\\?",\\?"([^"\\]+)'
)
NO_LINK_GRACE_PERIOD_MS = 5000


@dataclass
class CapturedBookingResponse:
    captured_at: str
    page_url: str
    response_url: str
    status: int
    ok: bool
    method: str
    resource_type: str
    request_headers: dict[str, str]
    response_headers: dict[str, str]
    post_data: str | None
    response_text: str
    booking_links: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _iter_response_roots(value: Any):
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
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.isdigit() and i + 1 < len(lines):
            decoded = _maybe_parse_json_string(lines[i + 1])
            if decoded is not None:
                yield decoded
                i += 2
                continue

        decoded = _maybe_parse_json_string(line)
        if decoded is not None:
            yield decoded
        i += 1


def _iter_nested_values(value: Any):
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


def _extract_u_param_from_pairs(value: Any) -> str | None:
    if not isinstance(value, list):
        return None

    for item in value:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and item[0] == "u"
            and isinstance(item[1], str)
        ):
            return item[1]
    return None


def _extract_booking_links_from_structured_response(response_text: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for value in _iter_nested_values(response_text):
        if (
            isinstance(value, list)
            and len(value) >= 2
            and value[0] == BOOKING_LINK_BASE
        ):
            token = _extract_u_param_from_pairs(value[1])
            if token is None:
                continue

            link = f"{BOOKING_LINK_BASE}?{urlencode({'u': token})}"
            if link not in seen:
                seen.add(link)
                links.append(link)

    return links


def _extract_booking_links(response_text: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for link in _extract_booking_links_from_structured_response(response_text):
        seen.add(link)
        links.append(link)

    for token in BOOKING_LINK_PATTERN.findall(response_text):
        link = f"{BOOKING_LINK_BASE}?{urlencode({'u': token})}"
        if link not in seen:
            seen.add(link)
            links.append(link)

    return links


async def _capture_response(response: Response, page: Page) -> CapturedBookingResponse:
    request = response.request
    post_data = request.post_data
    response_text = await response.text()

    return CapturedBookingResponse(
        captured_at=datetime.now(timezone.utc).isoformat(),
        page_url=page.url,
        response_url=response.url,
        status=response.status,
        ok=response.ok,
        method=request.method,
        resource_type=request.resource_type,
        request_headers=await request.all_headers(),
        response_headers=await response.all_headers(),
        post_data=post_data,
        response_text=response_text,
        booking_links=_extract_booking_links(response_text),
    )


def _write_capture(output_dir: Path, capture: CapturedBookingResponse) -> Path:
    output_path = _ensure_dir(output_dir) / f"{_timestamp()}.json"
    output_path.write_text(
        json.dumps(capture.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


async def capture_booking_results(
    *,
    url: str,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    headless: bool = False,
    timeout_ms: int = 300000,
    max_matches: int | None = None,
) -> list[Path]:
    output_dir = Path(output_dir)
    saved_paths: list[Path] = []
    done = asyncio.Event()
    pending_tasks: set[asyncio.Task[None]] = set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        async def handle_response(response: Response) -> None:
            if BOOKING_RESULTS_URL_PART not in response.url:
                return

            capture = await _capture_response(response, page)
            saved_path = _write_capture(output_dir, capture)
            saved_paths.append(saved_path)
            print(
                f"[capture {len(saved_paths)}] status={capture.status} "
                f"url={capture.response_url}"
            )
            for booking_link in capture.booking_links:
                print(f"[booking_link] {booking_link}")
            print(f"[saved] {saved_path}")

            if max_matches is not None and len(saved_paths) >= max_matches:
                done.set()

        def schedule_response_capture(response: Response) -> None:
            task = asyncio.create_task(handle_response(response))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

        page.on("response", schedule_response_capture)
        await page.goto(url, wait_until="domcontentloaded")

        if max_matches is None:
            try:
                await asyncio.wait_for(done.wait(), timeout=timeout_ms / 1000)
            except TimeoutError:
                pass
        else:
            await asyncio.wait_for(done.wait(), timeout=timeout_ms / 1000)

        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        await context.close()
        await browser.close()

    return saved_paths


async def fetch_booking_links(
    *,
    url: str,
    headless: bool = True,
    timeout_ms: int = 300000,
) -> list[str]:
    started_at = perf_counter()
    links: list[str] = []
    done = asyncio.Event()
    booking_response_seen = asyncio.Event()
    pending_tasks: set[asyncio.Task[None]] = set()
    first_link_lock = asyncio.Lock()
    booking_response_elapsed_s: float | None = None

    logger.info(
        "Starting booking link fetch: headless=%s, timeout_ms=%d, url=%s",
        headless,
        timeout_ms,
        url,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        async def _finish(result: list[str]) -> list[str]:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            await context.close()
            await browser.close()
            return result

        async def handle_response(response: Response) -> None:
            nonlocal booking_response_elapsed_s
            if BOOKING_RESULTS_URL_PART not in response.url:
                return
            booking_response_seen.set()
            booking_response_elapsed_s = perf_counter() - started_at

            response_text = await response.text()
            extracted_links = _extract_booking_links(response_text)
            if not extracted_links:
                logger.warning(
                    "fetch_booking_links: booking response contained no extractable links; response prefix=%s",
                    response_text[:500].replace("\n", "\\n"),
                )
            else:
                logger.info(
                    "Booking response received: links=%d, elapsed=%.2fs, response_url=%s",
                    len(extracted_links),
                    booking_response_elapsed_s,
                    response.url,
                )

            link = extracted_links[0] if extracted_links else None
            if link is None:
                return

            async with first_link_lock:
                if links:
                    return
                links.append(link)
                done.set()

        def schedule_response_capture(response: Response) -> None:
            task = asyncio.create_task(handle_response(response))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

        page.on("response", schedule_response_capture)
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await asyncio.wait_for(booking_response_seen.wait(), timeout=timeout_ms / 1000)
        except TimeoutError:
            logger.warning(
                "fetch_booking_links: timed out waiting for booking response; current_page=%s, elapsed=%.2fs",
                page.url,
                perf_counter() - started_at,
            )
            return await _finish([])

        if not links:
            try:
                await asyncio.wait_for(done.wait(), timeout=NO_LINK_GRACE_PERIOD_MS / 1000)
            except TimeoutError:
                logger.warning(
                    "fetch_booking_links: no extractable booking links found after booking response; current_page=%s, elapsed=%.2fs",
                    page.url,
                    perf_counter() - started_at,
                )
                return await _finish([])

        result = await _finish(links)
        logger.info(
            "Finished booking link fetch: links=%d, response_seen_elapsed=%s, total_elapsed=%.2fs, url=%s",
            len(result),
            f"{booking_response_elapsed_s:.2f}s" if booking_response_elapsed_s is not None else "n/a",
            perf_counter() - started_at,
            url,
        )
        return result


async def fetch_booking_links_for_query(
    query: Query,
    *,
    headless: bool = True,
    timeout_ms: int = 300000,
) -> list[str]:
    return await fetch_booking_links(
        url=query.booking_url(),
        headless=headless,
        timeout_ms=timeout_ms,
    )


async def capture_booking_results_for_query(
    query: Query,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    headless: bool = False,
    timeout_ms: int = 300000,
    max_matches: int | None = None,
) -> list[Path]:
    return await capture_booking_results(
        url=query.booking_url(),
        output_dir=output_dir,
        headless=headless,
        timeout_ms=timeout_ms,
        max_matches=max_matches,
    )


async def keep_browser_open_and_capture(
    *,
    start_url: str = "https://www.google.com/travel/flights",
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    headless: bool = False,
) -> None:
    output_dir = Path(output_dir)
    pending_tasks: set[asyncio.Task[None]] = set()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context: BrowserContext = await browser.new_context()
        page = await context.new_page()

        async def handle_response(response: Response) -> None:
            if BOOKING_RESULTS_URL_PART not in response.url:
                return

            capture = await _capture_response(response, page)
            saved_path = _write_capture(output_dir, capture)
            print(
                f"[capture] status={capture.status} url={capture.response_url}\n"
                + "\n".join(
                    f"[booking_link] {booking_link}"
                    for booking_link in capture.booking_links
                )
                + ("\n" if capture.booking_links else "")
                + f"[saved] {saved_path}"
            )

        def schedule_response_capture(response: Response) -> None:
            task = asyncio.create_task(handle_response(response))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

        page.on("response", schedule_response_capture)
        await page.goto(start_url, wait_until="domcontentloaded")
        print(
            "Browser is open. Trigger booking options in Google Flights; "
            "matching responses will be written to disk. Press Ctrl+C to stop."
        )

        try:
            while True:
                await asyncio.sleep(1)
        finally:
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            await context.close()
            await browser.close()
