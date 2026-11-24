"""MCP 网关：把工具注册表暴露为 MCP / HTTP JSON。

* SDK 存在 → stdio MCP 服务（``python -m app.mcp.server``）；
* 缺依赖 → ``GET /mcp/tools`` 的 JSON 描述，Web 服务照常运行。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-11] 生态协议/执行环境
# 职责：MCP 网关：把工具注册表暴露为 MCP / HTTP JSON
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

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
