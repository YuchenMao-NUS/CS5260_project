"""Application logging setup and request-scoped log context."""

from __future__ import annotations

from contextvars import Context, ContextVar, copy_context
from datetime import UTC, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import shutil
import sys
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from smartflight.config import settings

LOG_RECORD_BUILTINS = set(logging.makeLogRecord({}).__dict__)
KNOWN_EXTRA_FIELDS = (
    "request_id",
    "session_id",
    "progress_id",
    "method",
    "path",
    "status_code",
    "elapsed_ms",
    "message_length",
    "flights_count",
    "result_set_id",
    "flight_id",
    "from_airport",
    "to_airport",
    "departure_date",
    "return_date",
    "trip",
    "results_count",
    "choices_count",
    "filtered_count",
    "provider",
    "operation",
    "retry_attempt",
    "timeout_ms",
    "error_code",
    "retryable",
    "error_message",
    "is_flight_related",
    "process_id",
)

_request_id: ContextVar[str | None] = ContextVar("smartflight_request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("smartflight_session_id", default=None)
_progress_id: ContextVar[str | None] = ContextVar("smartflight_progress_id", default=None)
_PROCESS_STARTUP_LOG_PATH: Path | None = None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _running_on_cloud_run() -> bool:
    return bool(os.getenv("K_SERVICE"))


def _file_logs_enabled() -> bool:
    return _env_bool("SMARTFLIGHT_ENABLE_FILE_LOGS", not _running_on_cloud_run())


def get_request_context() -> dict[str, str]:
    """Return the active request logging context."""
    return {
        key: value
        for key, value in {
            "request_id": _request_id.get(),
            "session_id": _session_id.get(),
            "progress_id": _progress_id.get(),
        }.items()
        if value
    }


def set_request_context(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    progress_id: str | None = None,
) -> None:
    """Set request-scoped logging context values for the current context."""
    if request_id is not None:
        _request_id.set(request_id)
    if session_id is not None:
        _session_id.set(session_id)
    if progress_id is not None:
        _progress_id.set(progress_id)


def clear_request_context() -> None:
    """Clear request-scoped logging context values for the current context."""
    _request_id.set(None)
    _session_id.set(None)
    _progress_id.set(None)


def copy_request_context() -> Context:
    """Copy the current context for use in manually created threads."""
    return copy_context()


class RequestContextFilter(logging.Filter):
    """Attach contextvars to each log record when explicit values are absent."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "process_id", None):
            setattr(record, "process_id", os.getpid())
        for key, value in get_request_context().items():
            if not getattr(record, key, None):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """Format records as Cloud Run-friendly JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in KNOWN_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        for key, value in record.__dict__.items():
            if key in LOG_RECORD_BUILTINS or key in payload or key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Readable local text formatter with structured fields appended."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = []
        for field in KNOWN_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                fields.append(f"{field}={value}")
        if fields:
            return f"{base} {' '.join(fields)}"
        return base


def _log_level() -> int:
    return getattr(logging, os.getenv("SMARTFLIGHT_LOG_LEVEL", "INFO").upper(), logging.INFO)


def _log_format() -> str:
    default = "json" if _running_on_cloud_run() else "text"
    value = os.getenv("SMARTFLIGHT_LOG_FORMAT", default).strip().lower()
    return "json" if value == "json" else "text"


def _logs_root() -> Path:
    return settings.PROJECT_ROOT / "backend" / "logs"


def _startup_log_path() -> Path:
    global _PROCESS_STARTUP_LOG_PATH
    if _PROCESS_STARTUP_LOG_PATH is not None:
        return _PROCESS_STARTUP_LOG_PATH
    now = datetime.now()
    log_dir = _logs_root() / "current" / now.strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)
    _PROCESS_STARTUP_LOG_PATH = log_dir / f"{now.strftime('%Y%m%d-%H%M%S')}-p{os.getpid()}.log"
    return _PROCESS_STARTUP_LOG_PATH


def _daily_log_path() -> Path:
    now = datetime.now()
    log_dir = _logs_root() / "current" / now.strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / os.getenv("SMARTFLIGHT_LOG_FILE_NAME", "app.log")


def _file_log_path() -> Path:
    mode = os.getenv("SMARTFLIGHT_LOG_FILE_MODE", "daily").strip().lower()
    if mode == "startup":
        return _startup_log_path()
    return _daily_log_path()


def cleanup_log_archives() -> None:
    """Archive or delete non-today local log folders. Safe to call repeatedly."""
    if not _file_logs_enabled():
        return

    archive_days = _env_int("SMARTFLIGHT_LOG_ARCHIVE_DAYS", 7)
    logs_root = _logs_root()
    current_root = logs_root / "current"
    archive_root = logs_root / "archive"
    today = datetime.now().strftime("%Y-%m-%d")

    if archive_days == 0:
        for path in (current_root, archive_root):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        return

    archive_root.mkdir(parents=True, exist_ok=True)
    if current_root.exists():
        for daily_dir in current_root.iterdir():
            if not daily_dir.is_dir() or daily_dir.name == today:
                continue
            archive_path = archive_root / f"{daily_dir.name}.zip"
            try:
                if not archive_path.exists():
                    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
                        for file_path in daily_dir.rglob("*"):
                            if file_path.is_file():
                                archive.write(file_path, file_path.relative_to(daily_dir))
                shutil.rmtree(daily_dir, ignore_errors=True)
            except OSError:
                continue

    cutoff = datetime.now().date() - timedelta(days=archive_days)
    for archive_path in archive_root.glob("*.zip"):
        try:
            archive_date = datetime.strptime(archive_path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if archive_date < cutoff:
            archive_path.unlink(missing_ok=True)


def _build_formatter() -> logging.Formatter:
    return JsonFormatter() if _log_format() == "json" else TextFormatter()


def _remove_smartflight_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_smartflight_handler", False):
            logger.removeHandler(handler)
            handler.close()


def configure_logging() -> None:
    """Configure SmartFlight, Uvicorn, and dependency logs idempotently."""
    level = _log_level()
    formatter = _build_formatter()
    context_filter = RequestContextFilter()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    _remove_smartflight_handlers(root_logger)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    stream_handler._smartflight_handler = True
    root_logger.addHandler(stream_handler)

    if _file_logs_enabled():
        cleanup_log_archives()
        file_handler = logging.FileHandler(_file_log_path(), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        file_handler._smartflight_handler = True
        root_logger.addHandler(file_handler)

    for logger_name in ("smartflight", "flights_search", "flights_search_mcp"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.propagate = True
        _remove_smartflight_handlers(logger)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.setLevel(level)
        logger.propagate = True
