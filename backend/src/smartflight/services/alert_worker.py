from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event, Thread
from time import sleep

from smartflight.agent.filter_flights import _matches_preferences, fetch_booking_url_for_choice
from smartflight.agent.search_flights import search_one_way, search_round_trip
from smartflight.services.alerts import (
    AlertRecord,
    list_active_alerts,
    mark_alert_completed,
    mark_alert_expired,
    mark_alert_error,
)
from smartflight.services.emailer import send_flight_alert_email

logger = logging.getLogger(__name__)

_worker_stop = Event()
_worker_thread: Thread | None = None


def _build_route_label(flight_query: dict) -> str:
    from_airport = flight_query.get("from_airport", "UNK")
    to_airports = flight_query.get("to_airports") or []
    to_label = to_airports[0] if len(to_airports) == 1 else ", ".join(to_airports) if to_airports else "anywhere"
    return f"{from_airport} -> {to_label}"


def _search_choices(flight_query: dict) -> list[dict]:
    trip = flight_query.get("trip")
    if trip == "round_trip":
        return search_round_trip(flight_query)
    return search_one_way(flight_query)


def _match_choices(choices: list[dict], preference: dict) -> list[dict]:
    return [choice for choice in choices if _matches_preferences(choice, preference or {})]


def _choice_to_email_row(choice: dict, query: dict) -> dict:
    first_leg = (choice.get("flights") or [None])[0]
    airline = (choice.get("airlines") or ["Unknown"])[0]
    stops = "Direct" if choice.get("is_direct") else f"{max(len(choice.get('flights') or []) - 1, 1)} stop(s)"
    booking_url = choice.get("booking_url") or fetch_booking_url_for_choice(choice, query)
    return {
        "airline": airline,
        "price": choice.get("price"),
        "stops": stops,
        "duration": f"{choice.get('duration')} min",
        "departure": f"{choice.get('from_airport')} {query.get('departure_date')}",
        "arrival": choice.get("to_airport"),
        "booking_url": booking_url or "Unavailable",
    }


def process_alert_once(alert: AlertRecord) -> None:
    now = datetime.now(timezone.utc)
    if alert.expires_at <= now:
        mark_alert_expired(alert.id)
        return

    choices = _search_choices(alert.flight_query)
    matched = _match_choices(choices, alert.flight_preference)
    if not matched:
        return

    shortlisted = matched[:3]
    rows = [_choice_to_email_row(choice, alert.flight_query) for choice in shortlisted]
    send_flight_alert_email(
        alert.email,
        rows,
        {
            "route": _build_route_label(alert.flight_query),
            "alert_id": alert.id,
        },
    )
    mark_alert_completed(alert.id)


def _worker_loop(interval_seconds: int) -> None:
    logger.info("Alert worker started. interval=%ss", interval_seconds)
    while not _worker_stop.is_set():
        alerts = list_active_alerts()
        for alert in alerts:
            if _worker_stop.is_set():
                break
            try:
                process_alert_once(alert)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Alert processing failed for %s: %s", alert.id, exc)
                mark_alert_error(alert.id, str(exc))
        sleep(max(interval_seconds, 5))
    logger.info("Alert worker stopped.")


def start_alert_worker(interval_seconds: int) -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return

    _worker_stop.clear()
    _worker_thread = Thread(target=_worker_loop, args=(interval_seconds,), daemon=True)
    _worker_thread.start()


def stop_alert_worker() -> None:
    _worker_stop.set()
