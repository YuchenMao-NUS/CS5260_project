"""Pytest fixtures."""
import pytest
from fastapi.testclient import TestClient

from smartflight.main import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)
