"""SmartFlight API - FastAPI backend."""
import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from smartflight.config import settings
from smartflight.logging_config import clear_request_context, configure_logging, set_request_context

configure_logging()
logger = logging.getLogger(__name__)

from smartflight.routers import chat  # noqa: E402


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


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log each backend request at the application boundary."""
    request_id = request.headers.get("x-request-id") or f"req-{uuid4()}"
    set_request_context(request_id=request_id)
    start = perf_counter()
    logger.info(
        "Request started",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
    )
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (perf_counter() - start) * 1000
        logger.exception(
            "Request failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
        raise
    finally:
        if "response" not in locals():
            clear_request_context()

    elapsed_ms = (perf_counter() - start) * 1000
    logger.info(
        "Request completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_ms": round(elapsed_ms, 1),
        },
    )
    clear_request_context()
    return response


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "smartflight-api"}


frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", SPAStaticFiles(directory=frontend_dist, html=True), name="frontend")
