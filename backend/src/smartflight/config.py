"""Configuration and environment variables."""


class Settings:
    """Application settings."""

    # API
    API_PREFIX: str = "/api"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()
