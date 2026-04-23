"""Stable MCP error helpers for flights_search_mcp."""

from __future__ import annotations

from typing import NoReturn

import httpx
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INTERNAL_ERROR, INVALID_PARAMS


class ValidationError(ValueError):
    """Raised when an MCP payload is well-formed JSON but semantically invalid."""


class UnsupportedUsageError(ValueError):
    """Raised when a valid payload requests a currently unsupported flow."""


def raise_validation_error(
    message: str,
    *,
    details: dict[str, object] | None = None,
    remediation: str = "Fix the request payload and retry.",
) -> NoReturn:
    _raise_tool_error(
        error_code="validation_error",
        mcp_code=INVALID_PARAMS,
        message=message,
        retryable=False,
        details=details,
        remediation=remediation,
    )


def raise_unsupported_usage(
    message: str,
    *,
    details: dict[str, object] | None = None,
    remediation: str = "Adjust the request to a supported usage shape and retry.",
) -> NoReturn:
    _raise_tool_error(
        error_code="unsupported_usage",
        mcp_code=INVALID_PARAMS,
        message=message,
        retryable=False,
        details=details,
        remediation=remediation,
    )


def raise_mapped_runtime_error(exc: Exception) -> NoReturn:
    """Convert expected runtime failures into stable MCP tool errors."""

    if isinstance(exc, httpx.HTTPError):
        _raise_tool_error(
            error_code="upstream_request_failed",
            mcp_code=INTERNAL_ERROR,
            message=str(exc),
            retryable=True,
            details={"exception_type": type(exc).__name__},
            remediation=(
                "Verify outbound network access to Google Flights and retry."
            ),
        )

    if isinstance(exc, RuntimeError):
        text = str(exc)
        if "Playwright runtime" in text:
            _raise_tool_error(
                error_code="playwright_missing",
                mcp_code=INTERNAL_ERROR,
                message=text,
                retryable=False,
                details={"exception_type": type(exc).__name__},
                remediation="Install project dependencies and retry.",
            )
        if "playwright install chromium" in text or "browser binary" in text:
            _raise_tool_error(
                error_code="browser_runtime_missing",
                mcp_code=INTERNAL_ERROR,
                message=text,
                retryable=False,
                details={"exception_type": type(exc).__name__},
                remediation="Run `python -m playwright install chromium` and retry.",
            )

    if isinstance(exc, ValueError):
        _raise_tool_error(
            error_code="upstream_response_invalid",
            mcp_code=INTERNAL_ERROR,
            message=str(exc),
            retryable=False,
            details={"exception_type": type(exc).__name__},
            remediation=(
                "Inspect upstream response changes or parser assumptions and retry."
            ),
        )

    raise exc


def _raise_tool_error(
    *,
    error_code: str,
    mcp_code: int,
    message: str,
    retryable: bool,
    details: dict[str, object] | None,
    remediation: str,
) -> NoReturn:
    raise McpError(
        ErrorData(
            code=mcp_code,
            message=message,
            data={
                "code": error_code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
                "remediation": remediation,
            },
        )
    )
