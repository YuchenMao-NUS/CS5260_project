"""MCP server package for flights_search."""

from __future__ import annotations

from typing import Any

__all__ = ["create_server"]


def __getattr__(name: str) -> Any:
    if name == "create_server":
        from .server import create_server

        return create_server
    raise AttributeError(name)
