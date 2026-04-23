"""Server bootstrap for the flights_search MCP adapter."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import register_tools

SERVER_NAME = "flights-search-mcp"
SERVER_INSTRUCTIONS = (
    "Thin MCP adapter over the local flights_search package. "
    "Use structured tool inputs and pass opaque selection handles through "
    "without decoding them client-side."
)


def create_server() -> FastMCP:
    server = FastMCP(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    register_tools(server)
    return server


def main() -> None:
    create_server().run("stdio")


if __name__ == "__main__":
    main()
