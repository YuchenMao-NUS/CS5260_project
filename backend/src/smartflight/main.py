"""SmartFlight API - FastAPI backend."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from smartflight.config import settings
from smartflight.routers import chat


class SPAStaticFiles(StaticFiles):
    """Serve the built SPA and fall back to index.html for client-side routes."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 404 and not path.startswith("api/"):
            return await super().get_response("index.html", scope)
        return response


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


frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", SPAStaticFiles(directory=frontend_dist, html=True), name="frontend")
