"""HTTP retrieval helpers for Google Flights search and booking pages."""

from __future__ import annotations

from dataclasses import dataclass, field
import time

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

DEFAULT_SEARCH_URL = "https://www.google.com/travel/flights/search"
DEFAULT_BOOKING_URL = "https://www.google.com/travel/flights/booking"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


@dataclass
class SearchHttpClient:
    """Minimal HTTP client for retrieving Google Flights pages."""

    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    headers: dict[str, str] = field(
        default_factory=lambda: {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "user-agent": DEFAULT_USER_AGENT,
        }
    )
    cookies: dict[str, str] = field(default_factory=dict)

    def fetch_search_html(self, params: dict[str, str]) -> str:
        """Fetch Google Flights search HTML for the encoded params."""

        return self._fetch_html(DEFAULT_SEARCH_URL, params)

    def fetch_booking_html(self, params: dict[str, str]) -> str:
        """Fetch Google Flights booking HTML for the encoded params."""

        return self._fetch_html(DEFAULT_BOOKING_URL, params)

    def _fetch_html(self, url: str, params: dict[str, str]) -> str:
        """Fetch a Google Flights HTML page for the encoded params."""

        import httpx

        attempts = self.max_retries + 1
        last_error: httpx.HTTPError | None = None

        for attempt in range(attempts):
            with httpx.Client(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                cookies=self.cookies,
            ) as client:
                try:
                    response = client.get(url, params=params)
                    if (
                        response.status_code in RETRYABLE_STATUS_CODES
                        and attempt < self.max_retries
                    ):
                        self._sleep_before_retry(attempt)
                        continue
                    response.raise_for_status()
                except httpx.RequestError as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise
                    self._sleep_before_retry(attempt)
                    continue

            self.cookies.update(response.cookies.items())
            return response.text

        if last_error is not None:
            raise last_error
        raise RuntimeError("HTTP retrieval failed without returning a response.")

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * (2**attempt))

def fetch_search_html(params: dict[str, str]) -> str:
    """Fetch Google Flights search HTML using the default client settings."""

    return SearchHttpClient().fetch_search_html(params)


def fetch_booking_html(params: dict[str, str]) -> str:
    """Fetch Google Flights booking HTML using the default client settings."""

    return SearchHttpClient().fetch_booking_html(params)
