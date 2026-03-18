"""SmartFlight API - FastAPI backend."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from smartflight.config import settings
from smartflight.routers import chat

app = FastAPI(
    title="SmartFlight API",
    description="Intelligent Flight-Discovery Agent - NUS CS5260 Project",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix=settings.API_PREFIX, tags=["chat"])


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "smartflight-api"}
