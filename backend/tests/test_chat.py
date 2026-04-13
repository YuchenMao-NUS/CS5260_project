"""Tests for chat API."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from smartflight.agent import extract_preference as extract_preference_module
from smartflight.agent import extract_query as extract_query_module
from smartflight.main import app
from smartflight.routers import chat as chat_router
from smartflight.services import nlu as nlu_service
from smartflight.services import progress as progress_service

client = TestClient(app)


def test_health_check():
    """Health endpoint returns ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_returns_intent():
    """Chat endpoint parses intent and returns reply."""
    resp = client.post("/api/chat", json={"message": "Singapore to Tokyo"})
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert data["intent"]["flight_query"]["from_airport"] == "SIN"
    assert any(airport in data["intent"]["flight_query"]["to_airports"] for airport in ["TYO", "HND", "NRT"])


def test_chat_round_trip():
    """Chat endpoint correctly parses a round-trip query."""
    resp = client.post("/api/chat", json={"message": "Round trip from Singapore to London next week"})
    assert resp.status_code == 200
    data = resp.json()
    query = data["intent"].get("flight_query", {})
    assert query.get("trip") == "round_trip"
    assert query.get("from_airport") == "SIN"
    assert any(airport in query.get("to_airports", []) for airport in ["LHR", "LGW", "LON", "STN"])
    assert query.get("return_date") is not None


def test_chat_with_context():
    """Chat endpoint correctly infers origin from context when omitted."""
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


def test_chat_same_origin_destination():
    """Chat endpoint handles identical origin and destination."""
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
