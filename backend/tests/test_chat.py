"""Tests for chat API."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from smartflight.agent import agent as agent_module
from smartflight.agent import extract_preference as extract_preference_module
from smartflight.agent import extract_query as extract_query_module
from smartflight.agent import filter_flights as filter_flights_module
from smartflight.main import app
from smartflight.routers import chat as chat_router
from smartflight.services import booking as booking_service
from smartflight.services import nlu as nlu_service
from smartflight.services import progress as progress_service
from smartflight.services.chat_formatting import format_demo_flight, format_graph_flight

client = TestClient(app)


def test_graph_memory_allows_fast_flights_msgpack_types():
    """Checkpoint serde should explicitly allow fast-flight dataclass deserialization."""

    allowed_types = getattr(agent_module.memory.serde, "_allowed_msgpack_modules", set())
    expected_types = {
        ("smartflight.agent.fast_flights.model", "Airline"),
        ("smartflight.agent.fast_flights.model", "Alliance"),
        ("smartflight.agent.fast_flights.model", "JsMetadata"),
        ("smartflight.agent.fast_flights.model", "Airport"),
        ("smartflight.agent.fast_flights.model", "SimpleDatetime"),
        ("smartflight.agent.fast_flights.model", "SingleFlight"),
        ("smartflight.agent.fast_flights.model", "CarbonEmission"),
        ("smartflight.agent.fast_flights.model", "Flights"),
    }
    assert expected_types.issubset(allowed_types)


def _mock_chat_request_sync(monkeypatch, response: chat_router.ChatResponse) -> None:
    """Stub the synchronous chat pipeline for HTTP-layer unit tests."""

    def fake_run_chat_request_sync(message, user_context, session_id, progress_id=None, on_event=None):
        if on_event:
            on_event({"type": "completed", "data": response})
        return response

    monkeypatch.setattr(chat_router, "_run_chat_request_sync", fake_run_chat_request_sync)


def test_health_check():
    """Health endpoint returns ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_returns_intent(monkeypatch):
    """Chat endpoint returns the mocked parsed intent payload."""
    _mock_chat_request_sync(
        monkeypatch,
        chat_router.ChatResponse(
            reply="Found 1 flight option(s) from SIN to TYO. See details below.",
            flights=None,
            description_of_recommendation="Mocked summary",
            intent={
                "flight_query": {
                    "from_airport": "SIN",
                    "to_airports": ["TYO"],
                    "trip": "one_way",
                },
                "flight_preference": {},
                "error_message": None,
            },
        ),
    )

    resp = client.post("/api/chat", json={"message": "Singapore to Tokyo"})
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert data["intent"]["flight_query"]["from_airport"] == "SIN"
    assert any(airport in data["intent"]["flight_query"]["to_airports"] for airport in ["TYO", "HND", "NRT"])


def test_chat_round_trip(monkeypatch):
    """Chat endpoint returns a mocked round-trip intent."""
    _mock_chat_request_sync(
        monkeypatch,
        chat_router.ChatResponse(
            reply="Found 2 flight option(s) from SIN to LON on 2026-04-22 (returning 2026-04-29). See details below.",
            flights=None,
            description_of_recommendation="Mocked summary",
            intent={
                "flight_query": {
                    "from_airport": "SIN",
                    "to_airports": ["LON"],
                    "trip": "round_trip",
                    "return_date": "2026-04-29",
                },
                "flight_preference": {},
                "error_message": None,
            },
        ),
    )

    resp = client.post("/api/chat", json={"message": "Round trip from Singapore to London next week"})
    assert resp.status_code == 200
    data = resp.json()
    query = data["intent"].get("flight_query", {})
    assert query.get("trip") == "round_trip"
    assert query.get("from_airport") == "SIN"
    assert any(airport in query.get("to_airports", []) for airport in ["LHR", "LGW", "LON", "STN"])
    assert query.get("return_date") == "2026-04-29"


def test_chat_with_context(monkeypatch):
    """Chat endpoint uses a mocked response for context-based inference."""
    _mock_chat_request_sync(
        monkeypatch,
        chat_router.ChatResponse(
            reply="Found 1 flight option(s) from SIN to TYO. See details below.",
            flights=None,
            description_of_recommendation="Mocked summary",
            intent={
                "flight_query": {
                    "from_airport": "SIN",
                    "to_airports": ["TYO"],
                    "trip": "one_way",
                },
                "flight_preference": {},
                "error_message": None,
            },
        ),
    )

    resp = client.post(
        "/api/chat", 
        json={
            "message": "I want to go to Tokyo",
            "context": {
                "location": "Singapore, Singapore",
                "timeZone": "Asia/Singapore"
            }
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    query = data["intent"].get("flight_query", {})
    # Should infer SIN from context
    assert query.get("from_airport") == "SIN"
    assert any(airport in query.get("to_airports", []) for airport in ["TYO", "HND", "NRT"])


def test_chat_same_origin_destination(monkeypatch):
    """Chat endpoint returns a mocked validation error for invalid routes."""
    _mock_chat_request_sync(
        monkeypatch,
        chat_router.ChatResponse(
            reply="Your origin and destination both seem to be SIN. Please specify a different destination.",
            flights=None,
            description_of_recommendation=None,
            intent={
                "flight_query": None,
                "flight_preference": {},
                "error_message": "Your origin and destination both seem to be SIN. Please specify a different destination.",
            },
        ),
    )

    resp = client.post(
        "/api/chat", 
        json={
            "message": "Flight from Singapore to Singapore",
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    # Expect an error message and no flight query
    assert data["intent"].get("flight_query") is None
    assert data["intent"].get("error_message") is not None
    assert "different destination" in data["intent"].get("error_message").lower()


def test_chat_stream_emits_progress_and_completed(monkeypatch):
    """Streaming chat endpoint emits progress updates and a final payload."""

    def fake_run_chat_request_sync(message, user_context, session_id, progress_id=None, on_event=None):
        response = chat_router.ChatResponse(
            reply="Done",
            flights=None,
            description_of_recommendation=None,
            intent={"flight_query": {"from_airport": "SIN"}},
        )
        if on_event:
            on_event(
                {
                    "type": "progress",
                    "stage": "searching_flights",
                    "message": "Searching flights...",
                }
            )
            on_event({"type": "completed", "data": response})
        return response

    monkeypatch.setattr(chat_router, "_run_chat_request_sync", fake_run_chat_request_sync)

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "stream test", "session_id": "stream-test"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = []
    for chunk in body.strip().split("\n\n"):
        if not chunk.startswith("data: "):
            continue
        events.append(json.loads(chunk[6:]))

    assert any(event.get("type") == "progress" for event in events)
    assert any(event.get("type") == "completed" for event in events)
    completed_event = next(event for event in events if event.get("type") == "completed")
    assert completed_event["data"]["reply"] == "Done"


def test_chat_request_generates_unique_session_ids_by_default():
    """Chat request defaults should not share the same session id."""
    req_a = chat_router.ChatRequest(message="hello")
    req_b = chat_router.ChatRequest(message="hello")

    assert req_a.session_id != req_b.session_id
    assert req_a.session_id.startswith("chat-")
    assert req_b.session_id.startswith("chat-")


def test_stream_requests_generate_unique_progress_ids_per_session(monkeypatch):
    """Streaming requests should isolate progress channels even within one chat session."""
    registered_ids: list[str] = []
    original_register = chat_router.register_progress_queue

    def tracking_register(progress_id: str):
        registered_ids.append(progress_id)
        return original_register(progress_id)

    def fake_run_chat_request_sync(message, user_context, session_id, progress_id=None, on_event=None):
        response = chat_router.ChatResponse(
            reply=f"Done: {message}",
            flights=None,
            description_of_recommendation=None,
            intent={"flight_query": {"from_airport": "SIN"}},
        )
        if on_event:
            on_event({"type": "completed", "data": response})
        return response

    monkeypatch.setattr(chat_router, "register_progress_queue", tracking_register)
    monkeypatch.setattr(chat_router, "_run_chat_request_sync", fake_run_chat_request_sync)

    for message in ("first", "second"):
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": message, "session_id": "shared-session"},
        ) as response:
            assert response.status_code == 200
            _ = "".join(response.iter_text())

    assert len(registered_ids) == 2
    assert registered_ids[0] != registered_ids[1]
    assert all(progress_id.startswith("shared-session:stream:") for progress_id in registered_ids)


def test_run_flight_search_generates_unique_default_session_ids(monkeypatch):
    """NLU service should not fall back to a shared session id."""
    captured_ids: list[str] = []

    def fake_invoke(input_state, config=None):
        captured_ids.append(config["configurable"]["thread_id"])
        return {
            "user_input": input_state["user_input"],
            "flight_query": None,
            "flight_preference": None,
            "error_message": None,
            "flight_choices": None,
        }

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    nlu_service.run_flight_search("first")
    nlu_service.run_flight_search("second")

    assert len(captured_ids) == 2
    assert captured_ids[0] != captured_ids[1]
    assert all(session_id.startswith("chat-") for session_id in captured_ids)


def test_run_flight_search_falls_back_without_error(monkeypatch):
    """Fallback parsing should still return a usable non-error result."""

    def fake_invoke(input_state, config=None):
        raise RuntimeError("synthetic llm failure")

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    result = nlu_service.run_flight_search("demo flight to tokyo")

    assert result["error_message"] is None
    assert result["flight_query"]["from_airport"] == "SIN"
    assert result["flight_query"]["to_airports"] == ["TYO"]


def test_run_flight_search_fallback_explicit_route_excludes_origin_from_destinations(monkeypatch):
    """Fallback parsing should not include the explicit origin in destination results."""

    def fake_invoke(input_state, config=None):
        raise RuntimeError("synthetic llm failure")

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    result = nlu_service.run_flight_search("Singapore to Tokyo")

    assert result["error_message"] is None
    assert result["flight_query"]["from_airport"] == "SIN"
    assert result["flight_query"]["to_airports"] == ["TYO"]


def test_run_flight_search_fallback_same_origin_returns_validation_error(monkeypatch):
    """Fallback parsing should preserve same-origin validation behavior."""

    def fake_invoke(input_state, config=None):
        raise RuntimeError("synthetic llm failure")

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    result = nlu_service.run_flight_search("Flight from Singapore to Singapore")

    assert result["flight_query"] is None
    assert result["error_message"] is not None
    assert "different destination" in result["error_message"].lower()


def test_run_flight_search_fallback_uses_context_and_previous_state(monkeypatch):
    """Fallback parsing should reuse prior state and user context when available."""

    def fake_get_state(config):
        assert config["configurable"]["thread_id"] == "shared-session"
        return SimpleNamespace(
            values={
                "flight_query": {
                    "to_airports": ["TYO"],
                    "trip": "one_way",
                    "passengers": 2,
                    "seat_classes": "business",
                },
                "flight_preference": {
                    "preferred_airlines": ["SQ"],
                },
            }
        )

    def fake_invoke(input_state, config=None):
        raise RuntimeError("synthetic llm failure")

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "get_state", fake_get_state)
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    result = nlu_service.run_flight_search(
        "keep it direct under 500",
        user_context={"location": "Singapore, Singapore", "timeZone": "Asia/Singapore"},
        session_id="shared-session",
    )

    assert result["error_message"] is None
    assert result["flight_query"]["from_airport"] == "SIN"
    assert result["flight_query"]["to_airports"] == ["TYO"]
    assert result["flight_query"]["passengers"] == 2
    assert result["flight_query"]["seat_classes"] == "business"
    assert result["flight_preference"]["preferred_airlines"] == ["SQ"]
    assert result["flight_preference"]["direct_only"] is True
    assert result["flight_preference"]["max_price"] == 500.0


def test_run_flight_search_seeds_graph_with_checkpointed_memory(monkeypatch):
    """Successful graph invocations should receive prior query and preference state."""

    previous_state = {
        "flight_query": {
            "from_airport": "SIN",
            "to_airports": ["TYO"],
            "trip": "one_way",
            "departure_date": "2026-05-01",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        },
        "flight_preference": {
            "preferred_airlines": ["SQ"],
            "direct_only": True,
        },
        "flight_choices": [{"to_airport": "TYO"}],
        "error_message": "old error",
    }

    captured_input_state: dict | None = None

    def fake_get_state(config):
        assert config["configurable"]["thread_id"] == "memory-session"
        return SimpleNamespace(values=previous_state)

    def fake_invoke(input_state, config=None):
        nonlocal captured_input_state
        captured_input_state = input_state
        return {
            "user_input": input_state["user_input"],
            "flight_query": input_state["flight_query"],
            "flight_preference": input_state["flight_preference"],
            "error_message": input_state["error_message"],
            "flight_choices": input_state["flight_choices"],
        }

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "get_state", fake_get_state)
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    result = nlu_service.run_flight_search(
        "also keep it under 500",
        user_context={"location": "Singapore, Singapore"},
        session_id="memory-session",
        progress_id="progress-1",
    )

    assert captured_input_state is not None
    assert captured_input_state["flight_query"] == previous_state["flight_query"]
    assert captured_input_state["flight_preference"] == previous_state["flight_preference"]
    assert captured_input_state["flight_choices"] is None
    assert captured_input_state["error_message"] is None
    assert result["flight_query"] == previous_state["flight_query"]
    assert result["flight_preference"] == previous_state["flight_preference"]


def test_run_flight_search_fallback_survives_state_lookup_failure(monkeypatch):
    """Fallback should still work when previous-state lookup fails."""

    def fake_get_state(config):
        raise RuntimeError("state lookup failed")

    def fake_invoke(input_state, config=None):
        raise RuntimeError("synthetic llm failure")

    monkeypatch.setattr(nlu_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(nlu_service.graph, "get_state", fake_get_state)
    monkeypatch.setattr(nlu_service.graph, "invoke", fake_invoke)

    result = nlu_service.run_flight_search("Singapore to Tokyo", session_id="state-failure-session")

    assert result["error_message"] is None
    assert result["flight_query"]["from_airport"] == "SIN"
    assert result["flight_query"]["to_airports"] == ["TYO"]


def test_chat_demo_uses_fallback_query_without_short_circuit(monkeypatch):
    """Chat formatting should still return demo flights for a fallback result."""

    def fake_run_flight_search(message, user_context=None, session_id=None, progress_id=None):
        return {
            "user_input": message,
            "flight_query": {
                "from_airport": "SIN",
                "to_airports": ["TYO"],
                "departure_date": "2026-04-15",
                "return_date": None,
                "passengers": 1,
                "seat_classes": "economy",
                "trip": "one_way",
            },
            "flight_preference": {},
            "error_message": None,
            "flight_choices": None,
        }

    monkeypatch.setattr(chat_router, "run_flight_search", fake_run_flight_search)

    resp = client.post("/api/chat", json={"message": "demo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"].startswith("Found ")
    assert data["flights"]


def test_chat_live_results_do_not_eagerly_include_booking_urls(monkeypatch):
    """Live results should defer booking-link resolution until the Book button is clicked."""

    def fake_run_flight_search(message, user_context=None, session_id=None, progress_id=None):
        return {
            "user_input": message,
            "flight_query": {
                "from_airport": "SIN",
                "to_airports": ["TYO"],
                "departure_date": "2026-04-15",
                "return_date": None,
                "passengers": 1,
                "seat_classes": "economy",
                "trip": "one_way",
            },
            "flight_preference": {},
            "error_message": None,
            "flight_choices": [
                {
                    "trip": "one_way",
                    "from_airport": "SIN",
                    "to_airport": "TYO",
                    "departure_date": "2026-04-15",
                    "return_date": None,
                    "booking_url": None,
                    "tfu_token": None,
                    "is_direct": True,
                    "airlines": ["SQ"],
                    "price": 420.0,
                    "duration": 430,
                    "flights": [
                        SimpleNamespace(
                            from_airport=SimpleNamespace(code="SIN"),
                            to_airport=SimpleNamespace(code="TYO"),
                            departure=SimpleNamespace(date=(2026, 4, 15), time=(8, 0)),
                            arrival=SimpleNamespace(date=(2026, 4, 15), time=(16, 0)),
                            duration=430,
                            flight_number="SQ12",
                            flight_number_airline_code="SQ",
                        )
                    ],
                    "is_direct_2": None,
                    "airlines_2": None,
                    "price_2": None,
                    "duration_2": None,
                    "flights_2": None,
                }
            ],
        }

    monkeypatch.setattr(chat_router, "run_flight_search", fake_run_flight_search)

    resp = client.post("/api/chat", json={"message": "Singapore to Tokyo", "session_id": "live-no-booking"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["flights"][0]["id"] == "result-1"
    assert data["flights"][0]["bookingUrl"] is None


def test_booking_url_endpoint_returns_lazy_booking_url(monkeypatch):
    """The booking-url endpoint should return the resolved URL for a valid session and flight."""

    monkeypatch.setattr(
        chat_router,
        "resolve_booking_url",
        lambda session_id, result_set_id, flight_id: "https://booking.example/flight",
    )

    resp = client.post(
        "/api/chat/booking-url",
        json={
            "session_id": "booking-session",
            "result_set_id": "result-set-1",
            "flight_id": "result-1",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"bookingUrl": "https://booking.example/flight"}


def test_booking_url_endpoint_propagates_not_found(monkeypatch):
    """Unknown sessions or flights should surface as normal HTTP errors."""

    def fake_resolve_booking_url(session_id, result_set_id, flight_id):
        raise HTTPException(status_code=404, detail="Flight not found in this response.")

    monkeypatch.setattr(chat_router, "resolve_booking_url", fake_resolve_booking_url)

    resp = client.post(
        "/api/chat/booking-url",
        json={
            "session_id": "missing-session",
            "result_set_id": "result-set-404",
            "flight_id": "result-99",
        },
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Flight not found in this response."


def test_resolve_booking_url_maps_flight_id_within_saved_result_set(monkeypatch):
    """Flight ids should resolve against the specific saved response payload."""

    captured: dict | None = None

    def fake_fetch_booking_url_for_choice(choice, flight_query):
        nonlocal captured
        captured = {"choice": choice, "flight_query": flight_query}
        return "https://booking.example/selected"

    monkeypatch.setattr(booking_service, "fetch_booking_url_for_choice", fake_fetch_booking_url_for_choice)
    booking_service.store_result_set(
        "mapping-session",
        "result-set-1",
        {
            "trip": "one_way",
            "from_airport": "SIN",
            "to_airports": ["TYO"],
            "departure_date": "2026-05-01",
            "return_date": None,
            "seat_classes": "economy",
            "passengers": 1,
            "is_multi_destination": False,
            "description_of_recommendation": None,
        },
        flight_choices=[
            {"from_airport": "SIN", "to_airport": "LON", "trip": "one_way"},
            {"from_airport": "SIN", "to_airport": "TYO", "trip": "one_way"},
        ],
    )

    booking_url = booking_service.resolve_booking_url("mapping-session", "result-set-1", "result-2")

    assert booking_url == "https://booking.example/selected"
    assert captured is not None
    assert captured["choice"]["to_airport"] == "TYO"
    assert captured["flight_query"]["from_airport"] == "SIN"


def test_resolve_booking_url_keeps_older_result_sets_addressable(monkeypatch):
    """Older chat messages should continue resolving against their own saved result set."""

    seen_destinations: list[str] = []

    def fake_fetch_booking_url_for_choice(choice, flight_query):
        seen_destinations.append(choice["to_airport"])
        return f"https://booking.example/{choice['to_airport'].lower()}"

    monkeypatch.setattr(booking_service, "fetch_booking_url_for_choice", fake_fetch_booking_url_for_choice)

    booking_service.store_result_set(
        "history-session",
        "older-results",
        {"from_airport": "SIN", "to_airports": ["TYO"], "trip": "one_way"},
        flight_choices=[{"from_airport": "SIN", "to_airport": "TYO", "trip": "one_way"}],
    )
    booking_service.store_result_set(
        "history-session",
        "newer-results",
        {"from_airport": "SIN", "to_airports": ["LON"], "trip": "one_way"},
        flight_choices=[{"from_airport": "SIN", "to_airport": "LON", "trip": "one_way"}],
    )

    older_url = booking_service.resolve_booking_url("history-session", "older-results", "result-1")
    newer_url = booking_service.resolve_booking_url("history-session", "newer-results", "result-1")

    assert older_url == "https://booking.example/tyo"
    assert newer_url == "https://booking.example/lon"
    assert seen_destinations == ["TYO", "LON"]


def test_resolve_booking_url_prefers_saved_link_from_response(monkeypatch):
    """Saved booking URLs from the original response should be reused directly."""

    def fail_fetch_booking_url_for_choice(choice, flight_query):
        raise AssertionError("lazy booking lookup should not run when response already has a link")

    monkeypatch.setattr(booking_service, "fetch_booking_url_for_choice", fail_fetch_booking_url_for_choice)

    booking_service.store_result_set(
        "saved-link-session",
        "saved-link-results",
        {"from_airport": "SIN", "to_airports": ["TYO"], "trip": "one_way"},
        flight_choices=[
            {
                "from_airport": "SIN",
                "to_airport": "TYO",
                "trip": "one_way",
                "booking_url": "https://booking.example/already-saved",
            }
        ],
    )

    booking_url = booking_service.resolve_booking_url("saved-link-session", "saved-link-results", "result-1")

    assert booking_url == "https://booking.example/already-saved"


def test_fetch_one_way_booking_url_retries_once_with_short_timeout(monkeypatch):
    """One-way booking lookup should use a 5-second timeout and retry once."""

    calls: list[int] = []

    def fake_asyncio_run(coroutine):
        calls.append(filter_flights_module.BOOKING_URL_FETCH_TIMEOUT_MS)
        coroutine.close()
        if len(calls) == 1:
            raise TimeoutError("first attempt timed out")
        return ["https://booking.example/retried"]

    monkeypatch.setattr(filter_flights_module.asyncio, "run", fake_asyncio_run)

    flight_segment = SimpleNamespace(
        from_airport=SimpleNamespace(code="SIN"),
        to_airport=SimpleNamespace(code="TYO"),
        flight_number_airline_code="SQ",
        flight_number_numeric="638",
        departure=SimpleNamespace(date=(2026, 5, 1)),
    )

    booking_url = filter_flights_module._fetch_one_way_booking_url(
        from_airport="SIN",
        to_airport="TYO",
        departure_date="2026-05-01",
        seat_class="economy",
        passengers=1,
        flight_result=[flight_segment],
    )

    assert booking_url == "https://booking.example/retried"
    assert len(calls) == 2


def test_extract_preference_merges_with_existing_state(monkeypatch):
    """Preference extraction should preserve prior values that were not updated this turn."""

    class FakeCompletions:
        @staticmethod
        def parse(*args, **kwargs):
            parsed = extract_preference_module.FlightPreferenceExtraction(
                direct_only=None,
                preferred_airlines=None,
                max_price=500.0,
                min_price=None,
                max_duration=None,
                min_duration=None,
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
            )

    class FakeOpenAIClient:
        def __init__(self, *args, **kwargs):
            self.beta = SimpleNamespace(
                chat=SimpleNamespace(completions=FakeCompletions())
            )

    monkeypatch.setattr(extract_preference_module.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(extract_preference_module, "OpenAI", FakeOpenAIClient)

    result = extract_preference_module.extract_preference_node(
        {
            "session_id": "chat-session",
            "progress_id": None,
            "user_input": "also keep it under 500",
            "user_context": {},
            "flight_query": None,
            "flight_preference": {
                "preferred_airlines": ["SQ"],
                "direct_only": True,
            },
            "flight_choices": None,
            "error_message": None,
        }
    )

    assert result["flight_preference"]["preferred_airlines"] == ["SQ"]
    assert result["flight_preference"]["direct_only"] is True
    assert result["flight_preference"]["max_price"] == 500.0


def test_extract_preference_applies_structured_ui_filters(monkeypatch):
    """Structured frontend filters should update preference memory without polluting user text."""

    class FakeCompletions:
        @staticmethod
        def parse(*args, **kwargs):
            parsed = extract_preference_module.FlightPreferenceExtraction(
                direct_only=None,
                max_stops=None,
                min_stops=None,
                preferred_airlines=None,
                max_price=None,
                min_price=None,
                max_duration=None,
                min_duration=None,
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
            )

    class FakeOpenAIClient:
        def __init__(self, *args, **kwargs):
            self.beta = SimpleNamespace(
                chat=SimpleNamespace(completions=FakeCompletions())
            )

    monkeypatch.setattr(extract_preference_module.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(extract_preference_module, "OpenAI", FakeOpenAIClient)

    result = extract_preference_module.extract_preference_node(
        {
            "session_id": "chat-session",
            "progress_id": None,
            "user_input": "return after 1 week",
            "user_context": {
                "filters": [
                    {"id": "stops", "label": "Max 1 stop"},
                    {"id": "airline-SQ", "label": "Singapore Airlines"},
                ]
            },
            "flight_query": None,
            "flight_preference": {},
            "flight_choices": None,
            "error_message": None,
        }
    )

    assert result["flight_preference"]["direct_only"] is False
    assert result["flight_preference"]["max_stops"] == 1
    assert result["flight_preference"]["min_stops"] is None
    assert result["flight_preference"]["preferred_airlines"] == ["SQ"]


def test_filter_flights_clears_stale_choices_when_search_returns_none():
    """Empty search results should clear any checkpointed flight choices."""

    result = filter_flights_module.filter_flights_node(
        {
            "session_id": "chat-session",
            "progress_id": None,
            "user_input": "Tokyo please",
            "user_context": {},
            "flight_query": {
                "trip": "one_way",
                "from_airport": "SIN",
                "to_airports": ["TYO"],
                "departure_date": "2026-05-01",
                "return_date": None,
                "seat_classes": "economy",
                "passengers": 1,
                "is_multi_destination": False,
                "description_of_recommendation": None,
            },
            "flight_preference": {},
            "flight_choices": None,
            "error_message": None,
        }
    )

    assert result["flight_choices"] == []
    assert result["error_message"] is None


def test_filter_flights_honors_max_stops_preference():
    """Stop-count preferences from UI filters should participate in hard filtering."""

    one_stop_segments = [
        SimpleNamespace(
            from_airport=SimpleNamespace(code="SIN"),
            to_airport=SimpleNamespace(code="HKG"),
            departure=SimpleNamespace(date=(2026, 5, 1), time=(8, 0)),
            arrival=SimpleNamespace(date=(2026, 5, 1), time=(12, 0)),
            duration=240,
            flight_number="SQ001",
        ),
        SimpleNamespace(
            from_airport=SimpleNamespace(code="HKG"),
            to_airport=SimpleNamespace(code="TYO"),
            departure=SimpleNamespace(date=(2026, 5, 1), time=(13, 30)),
            arrival=SimpleNamespace(date=(2026, 5, 1), time=(19, 10)),
            duration=340,
            flight_number="SQ002",
        ),
    ]

    two_stop_segments = [
        SimpleNamespace(
            from_airport=SimpleNamespace(code="SIN"),
            to_airport=SimpleNamespace(code="HKG"),
            departure=SimpleNamespace(date=(2026, 5, 1), time=(7, 0)),
            arrival=SimpleNamespace(date=(2026, 5, 1), time=(11, 0)),
            duration=240,
            flight_number="CX101",
        ),
        SimpleNamespace(
            from_airport=SimpleNamespace(code="HKG"),
            to_airport=SimpleNamespace(code="TPE"),
            departure=SimpleNamespace(date=(2026, 5, 1), time=(12, 0)),
            arrival=SimpleNamespace(date=(2026, 5, 1), time=(14, 0)),
            duration=120,
            flight_number="CX102",
        ),
        SimpleNamespace(
            from_airport=SimpleNamespace(code="TPE"),
            to_airport=SimpleNamespace(code="TYO"),
            departure=SimpleNamespace(date=(2026, 5, 1), time=(15, 0)),
            arrival=SimpleNamespace(date=(2026, 5, 1), time=(19, 0)),
            duration=240,
            flight_number="CX103",
        ),
    ]

    result = filter_flights_module.filter_flights_node(
        {
            "session_id": "chat-session",
            "progress_id": None,
            "user_input": "return after 1 week",
            "user_context": {},
            "flight_query": {
                "trip": "one_way",
                "from_airport": "SIN",
                "to_airports": ["TYO"],
                "departure_date": "2026-05-01",
                "return_date": None,
                "seat_classes": "economy",
                "passengers": 1,
                "is_multi_destination": False,
                "description_of_recommendation": None,
            },
            "flight_preference": {
                "max_stops": 1,
            },
            "flight_choices": [
                {
                    "trip": "one_way",
                    "from_airport": "SIN",
                    "to_airport": "TYO",
                    "departure_date": "2026-05-01",
                    "return_date": None,
                    "booking_url": None,
                    "tfu_token": None,
                    "is_direct": False,
                    "airlines": ["SQ"],
                    "price": 420.0,
                    "duration": 430,
                    "flights": one_stop_segments,
                    "is_direct_2": None,
                    "airlines_2": None,
                    "price_2": None,
                    "duration_2": None,
                    "flights_2": None,
                },
                {
                    "trip": "one_way",
                    "from_airport": "SIN",
                    "to_airport": "TYO",
                    "departure_date": "2026-05-01",
                    "return_date": None,
                    "booking_url": None,
                    "tfu_token": None,
                    "is_direct": False,
                    "airlines": ["CX"],
                    "price": 380.0,
                    "duration": 600,
                    "flights": two_stop_segments,
                    "is_direct_2": None,
                    "airlines_2": None,
                    "price_2": None,
                    "duration_2": None,
                    "flights_2": None,
                },
            ],
            "error_message": None,
        }
    )

    assert len(result["flight_choices"]) == 1
    assert result["flight_choices"][0]["airlines"] == ["SQ"]


def test_extract_query_skips_openai_when_progress_cancelled(monkeypatch):
    """Cancelled analysis should stop before issuing a new OpenAI request."""
    progress_id = "cancel-before-analysis"
    progress_service.register_progress_queue(progress_id)
    progress_service.cancel_progress(progress_id)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("OpenAI should not be called after cancellation")

    monkeypatch.setattr(extract_query_module, "OpenAI", fail_if_called)

    try:
        with pytest.raises(progress_service.ProgressCancelledError):
            extract_query_module.extract_query_node(
                {
                    "session_id": "chat-session",
                    "progress_id": progress_id,
                    "user_input": "Singapore to Tokyo",
                    "user_context": {},
                    "flight_query": None,
                    "flight_preference": None,
                    "flight_choices": None,
                    "error_message": None,
                }
            )
    finally:
        progress_service.unregister_progress_queue(progress_id)


def test_progress_helpers_stop_emitting_after_cancellation():
    """Progress helpers should not enqueue new events after cancellation."""
    session_id = "cancel-test-session"
    queue = progress_service.register_progress_queue(session_id)
    try:
        progress_service.cancel_progress(session_id)
        progress_service.emit_progress(session_id, "searching_flights", "Searching...")
        progress_service.emit_completed(session_id, {"reply": "Done"})
        progress_service.emit_error(session_id, "Boom")
        assert queue.empty()
    finally:
        progress_service.unregister_progress_queue(session_id)

def test_format_graph_flight_preserves_stop_airports():
    """Graph flight formatting should keep layover airports in the response."""
    outbound_segments = [
        SimpleNamespace(
            from_airport=SimpleNamespace(code="SIN"),
            to_airport=SimpleNamespace(code="HKG"),
            departure=SimpleNamespace(date=(2026, 3, 14), time=(8, 0)),
            arrival=SimpleNamespace(date=(2026, 3, 14), time=(12, 0)),
            duration=240,
            flight_number="CX700",
            flight_number_airline_code="CX",
        ),
        SimpleNamespace(
            from_airport=SimpleNamespace(code="HKG"),
            to_airport=SimpleNamespace(code="NRT"),
            departure=SimpleNamespace(date=(2026, 3, 14), time=(13, 30)),
            arrival=SimpleNamespace(date=(2026, 3, 14), time=(18, 10)),
            duration=280,
            flight_number="CX520",
            flight_number_airline_code="CX",
        ),
    ]

    formatted = format_graph_flight(
        {
            "trip": "one_way",
            "price": 385.0,
            "duration": 520,
            "airlines": ["CX"],
            "flights": outbound_segments,
        },
        1,
    )

    leg = formatted["legs"][0]
    assert leg["stops"] == "1 stop (HKG)"
    assert leg["stopCount"] == 1
    assert leg["stopAirports"] == ["HKG"]


def test_format_demo_flight_derives_structured_stop_fields():
    """Demo flights should expose the same structured stop data as live results."""
    formatted = format_demo_flight(
        {
            "id": "demo-2",
            "price": 385.0,
            "legs": [
                {
                    "airlineCode": "CX",
                    "departure": "SIN 14:20",
                    "arrival": "NRT 21:45",
                    "duration": "6h 25m",
                    "duration_minutes": 385,
                    "stops": "1 stop (HKG)",
                }
            ],
        }
    )

    leg = formatted["legs"][0]
    assert leg["stopCount"] == 1
    assert leg["stopAirports"] == ["HKG"]
    assert leg["stops"] == "1 stop (HKG)"

def test_format_demo_flight_prefers_structured_stop_fields_over_legacy_label():
    """Demo leg normalization should not keep conflicting legacy and structured stop data."""
    formatted = format_demo_flight(
        {
            "id": "demo-conflict",
            "price": 500.0,
            "legs": [
                {
                    "airlineCode": "CX",
                    "departure": "SIN 14:20",
                    "arrival": "NRT 21:45",
                    "duration": "9h 40m",
                    "duration_minutes": 580,
                    "stops": "1 stop (HKG)",
                    "stopCount": 2,
                    "stopAirports": ["KUL", "BKK"],
                }
            ],
        }
    )

    leg = formatted["legs"][0]
    assert leg["stopCount"] == 2
    assert leg["stopAirports"] == ["KUL", "BKK"]
    assert leg["stops"] == "2 stops (KUL, BKK)"

