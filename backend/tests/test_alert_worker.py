from __future__ import annotations

from datetime import datetime, timedelta, timezone

from smartflight.services import alert_worker
from smartflight.services.alerts import create_alert, get_alert, clear_all_alerts


def _sample_choice() -> dict:
    return {
        "trip": "one_way",
        "from_airport": "SIN",
        "to_airport": "NRT",
        "departure_date": "2026-05-14",
        "return_date": None,
        "booking_url": None,
        "tfu_token": None,
        "is_direct": True,
        "airlines": ["SQ"],
        "price": 320.0,
        "duration": 420,
        "flights": [],
        "is_direct_2": None,
        "airlines_2": None,
        "price_2": None,
        "duration_2": None,
        "flights_2": None,
    }


def test_process_alert_once_marks_completed_and_sends_email(monkeypatch):
    clear_all_alerts()
    sent_payload = {}

    alert = create_alert(
        session_id="alert-session",
        email="traveler@example.com",
        flight_query={
            "trip": "one_way",
            "from_airport": "SIN",
            "to_airports": ["NRT"],
            "departure_date": "2026-05-14",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        },
        flight_preference={"max_price": 500.0},
    )

    monkeypatch.setattr(alert_worker, "_search_choices", lambda _: [_sample_choice()])
    monkeypatch.setattr(alert_worker, "fetch_booking_url_for_choice", lambda *_: "https://booking.example/flight")

    def fake_send(to_email, matches, context):
        sent_payload["to"] = to_email
        sent_payload["matches"] = matches
        sent_payload["context"] = context

    monkeypatch.setattr(alert_worker, "send_flight_alert_email", fake_send)

    alert_worker.process_alert_once(alert)

    saved = get_alert(alert.id)
    assert saved is not None
    assert saved.status == "completed"
    assert sent_payload["to"] == "traveler@example.com"
    assert sent_payload["matches"]
    assert sent_payload["matches"][0]["booking_url"] == "https://booking.example/flight"


def test_process_alert_once_keeps_active_when_no_match(monkeypatch):
    clear_all_alerts()
    alert = create_alert(
        session_id="alert-session",
        email="traveler@example.com",
        flight_query={
            "trip": "one_way",
            "from_airport": "SIN",
            "to_airports": ["NRT"],
            "departure_date": "2026-05-14",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        },
        flight_preference={"max_price": 100.0},
    )

    monkeypatch.setattr(alert_worker, "_search_choices", lambda _: [_sample_choice()])

    alert_worker.process_alert_once(alert)

    saved = get_alert(alert.id)
    assert saved is not None
    assert saved.status == "active"


def test_process_alert_once_marks_expired_when_ttl_passed():
    clear_all_alerts()
    alert = create_alert(
        session_id="alert-session",
        email="traveler@example.com",
        flight_query={
            "trip": "one_way",
            "from_airport": "SIN",
            "to_airports": ["NRT"],
            "departure_date": "2026-05-14",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        },
        flight_preference={"max_price": 500.0},
    )

    # Force expiry before processing.
    alert.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    alert_worker.process_alert_once(alert)

    saved = get_alert(alert.id)
    assert saved is not None
    assert saved.status == "expired"


def test_worker_loop_marks_error_when_processing_raises(monkeypatch):
    clear_all_alerts()
    alert = create_alert(
        session_id="alert-session",
        email="traveler@example.com",
        flight_query={
            "trip": "one_way",
            "from_airport": "SIN",
            "to_airports": ["NRT"],
            "departure_date": "2026-05-14",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        },
        flight_preference={"max_price": 500.0},
    )

    monkeypatch.setattr(alert_worker, "_search_choices", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(alert_worker, "sleep", lambda _: alert_worker._worker_stop.set())

    alert_worker._worker_stop.clear()
    alert_worker._worker_loop(5)

    saved = get_alert(alert.id)
    assert saved is not None
    assert saved.status == "error"
    assert saved.last_error is not None
    assert "boom" in saved.last_error
