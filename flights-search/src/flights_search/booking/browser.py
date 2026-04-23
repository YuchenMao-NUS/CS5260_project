"""Browser-driven booking capture for Google Flights."""

from __future__ import annotations

from urllib.parse import urlencode

from flights_search.client.http import DEFAULT_BOOKING_URL

BOOKING_RESULTS_URL_PART = (
    "/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/"
    "GetBookingResults"
)
DEFAULT_TIMEOUT_MS = 30_000
POST_RESPONSE_GRACE_MS = 1_000
PLAYWRIGHT_INSTALL_HINT = "python -m playwright install chromium"


def fetch_booking_result_texts(
    params: dict[str, str],
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    headless: bool = True,
) -> list[str]:
    """Capture raw GetBookingResults payloads for a booking page.

    The public booking page HTML is a JS shell; the actual booking-option data
    arrives through a browser-initiated XHR after the page loads.
    """

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(_missing_playwright_message()) from exc

    booking_url = f"{DEFAULT_BOOKING_URL}?{urlencode(params)}"
    payloads: list[str] = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except PlaywrightError as exc:
            raise RuntimeError(_missing_browser_message(exc)) from exc
        try:
            page = browser.new_page()

            def on_response(response) -> None:
                if BOOKING_RESULTS_URL_PART not in response.url:
                    return
                payloads.append(response.text())

            page.on("response", on_response)

            with page.expect_response(
                lambda response: BOOKING_RESULTS_URL_PART in response.url,
                timeout=timeout_ms,
            ):
                page.goto(
                    booking_url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

            page.wait_for_timeout(POST_RESPONSE_GRACE_MS)
        finally:
            browser.close()

    return payloads


def _missing_playwright_message() -> str:
    return (
        "Booking resolution requires the Playwright runtime. "
        "Install project dependencies and then run "
        f"`{PLAYWRIGHT_INSTALL_HINT}`."
    )


def _missing_browser_message(exc: Exception) -> str:
    return (
        "Booking resolution requires the Playwright Chromium browser binary. "
        f"Run `{PLAYWRIGHT_INSTALL_HINT}` and retry. Original error: {exc}"
    )
