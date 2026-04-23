"""Configuration and environment variables."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(BACKEND_ENV_FILE)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return float(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Application settings."""

    def __init__(self) -> None:
        project_root = Path(__file__).resolve().parents[3]
        flights_search_repo = project_root / "flights-search"

        self.API_PREFIX: str = "/api"
        self.CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
        self.OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
        self.PROJECT_ROOT: Path = project_root
        self.FLIGHTS_SEARCH_REPO: Path = Path(
            os.getenv("FLIGHTS_SEARCH_REPO", str(flights_search_repo))
        ).resolve()
        self.FLIGHTS_SEARCH_SRC: Path = self.FLIGHTS_SEARCH_REPO / "src"
        self.FLIGHTS_SEARCH_SERVER_PYTHON: str = os.getenv(
            "FLIGHTS_SEARCH_SERVER_PYTHON",
            sys.executable,
        )
        self.FLIGHTS_SEARCH_SERVER_MODULE: str = os.getenv(
            "FLIGHTS_SEARCH_SERVER_MODULE",
            "flights_search_mcp.server",
        )

        self.SMTP_HOST: str = os.getenv("SMTP_HOST", "")
        self.SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
        self.SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
        self.SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "")
        self.ALERT_CHECK_INTERVAL_SECONDS: int = int(os.getenv("ALERT_CHECK_INTERVAL_SECONDS", "300"))
        self.ALERT_TTL_HOURS: int = int(os.getenv("ALERT_TTL_HOURS", "24"))
        self.ENABLE_EMAIL_TEST_ENDPOINT: bool = _bool_env("ENABLE_EMAIL_TEST_ENDPOINT", False)

        # primp Google Flights fetch timeouts (seconds)
        self.FLIGHTS_HTTP_CONNECT_TIMEOUT_S: float = _float_env(
            "FLIGHTS_HTTP_CONNECT_TIMEOUT_S",
            8.0,
        )
        self.FLIGHTS_HTTP_READ_TIMEOUT_S: float = _float_env(
            "FLIGHTS_HTTP_READ_TIMEOUT_S",
            30.0,
        )
        # Hard ceiling for the entire search_one_way / search_round_trip call.
        # If the deadline is exceeded, remaining routes are skipped and
        # already-collected results are returned.
        self.FLIGHTS_SEARCH_DEADLINE_S: float = _float_env(
            "FLIGHTS_SEARCH_DEADLINE_S",
            90.0,
        )

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_USERNAME and self.SMTP_PASSWORD and self.SMTP_FROM_EMAIL)

    @property
    def openai_api_key(self) -> str | None:
        """Resolve the OpenAI API key from settings first, then the process environment."""
        return self.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

    @property
    def openai_enabled(self) -> bool:
        """Whether OpenAI-backed features are configured."""
        return bool(self.openai_api_key)


settings = Settings()
