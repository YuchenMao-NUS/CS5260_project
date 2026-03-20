"""Configuration and environment variables."""

from __future__ import annotations

import os


class Settings:
    """Application settings."""

    def __init__(self) -> None:
        self.API_PREFIX: str = "/api"
        self.CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
        self.OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

    @property
    def openai_api_key(self) -> str | None:
        """Resolve the OpenAI API key from settings first, then the process environment."""
        return self.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

    @property
    def openai_enabled(self) -> bool:
        """Whether OpenAI-backed features are configured."""
        return bool(self.openai_api_key)


settings = Settings()
