"""Standalone MCP server exposing the e-commerce business tools.

Run:
    python -m app.mcp.server --transport stdio
    python -m app.mcp.server --transport streamable-http   # http://127.0.0.1:8001/mcp
"""
from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from .tools import ALL_TOOL_FUNCTIONS

mcp = FastMCP("ecommerce-tools", host="127.0.0.1", port=8001,
              instructions="E-commerce product, order, refund and knowledge-base tools.")

for _fn in ALL_TOOL_FUNCTIONS:
    mcp.tool()(_fn)


def main() -> None:
    parser = argparse.ArgumentParser(description="E-commerce MCP server")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
