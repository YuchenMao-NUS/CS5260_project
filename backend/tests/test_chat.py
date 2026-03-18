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
    assert "TYO" in data["intent"]["flight_query"]["to_airports"]
