"""Tool loading: in-process adapters or remote MCP, then RBAC filtering."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from ..config import get_settings
from ..mcp.tools import ALL_TOOL_FUNCTIONS
from ..security.rbac import filter_tools


def local_tools() -> list[BaseTool]:
    """Wrap the exact MCP tool functions as LangChain tools (no network needed)."""
    return [
        StructuredTool.from_function(
            func=fn,
            name=fn.__name__,
            description=(fn.__doc__ or "").strip(),
        )
        for fn in ALL_TOOL_FUNCTIONS
    ]


async def load_agent_tools(user: Any, token: str | None = None) -> list[BaseTool]:
    """Load tools via the configured MCP transport and apply role-based filtering."""
    settings = get_settings()
    if settings.mcp_mode == "http":
        from langchain_mcp_adapters.client import MultiServerMCPClient

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        client = MultiServerMCPClient({
            "ecommerce": {"transport": "http", "url": settings.mcp_http_url,
                          "headers": headers}
        })
        tools = await client.get_tools()
    else:
        tools = local_tools()
    return filter_tools(tools, user)
