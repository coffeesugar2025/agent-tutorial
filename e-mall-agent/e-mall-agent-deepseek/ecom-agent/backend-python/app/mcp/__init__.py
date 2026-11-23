"""MCP 网关：把工具注册表暴露为 MCP / HTTP JSON。

* SDK 存在 → stdio MCP 服务（``python -m app.mcp.server``）；
* 缺依赖 → ``GET /mcp/tools`` 的 JSON 描述，Web 服务照常运行。
"""

from app.mcp.server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    build_server,
    call_tool,
    create_router,
    describe,
    list_tool_descriptors,
    mount,
    run_stdio,
    sdk_available,
    tools_payload,
)

__all__ = [
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "build_server",
    "call_tool",
    "create_router",
    "describe",
    "list_tool_descriptors",
    "mount",
    "run_stdio",
    "sdk_available",
    "tools_payload",
]
