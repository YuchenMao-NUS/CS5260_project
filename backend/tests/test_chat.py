"""Tests for chat API."""
from fastapi.testclient import TestClient

from smartflight.main import app

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
