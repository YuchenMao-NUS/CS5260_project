"""Configuration and environment variables."""

from __future__ import annotations

import os
import sys
from pathlib import Path


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

    @property
    def openai_api_key(self) -> str | None:
        """Resolve the OpenAI API key from settings first, then the process environment."""
        return self.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

    @property
    def openai_enabled(self) -> bool:
        """Whether OpenAI-backed features are configured."""
        return bool(self.openai_api_key)


settings = Settings()
