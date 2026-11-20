"""极简 MCP Server（JSON-RPC 2.0 over stdio）—— 只为讲清协议原理。

真实项目请用官方 SDK（Python `mcp` / TypeScript `@modelcontextprotocol/sdk`），
并处理鉴权、超时、并发、资源与 Prompt、以及新版规范的无状态 / Streamable HTTP 传输。

启动方式：客户端用子进程拉起本文件，往 stdin 逐行写 JSON-RPC，从 stdout 逐行读响应。
日志只能写 stderr —— 写 stdout 会污染协议流，这是 stdio 传输最常见的坑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import hr_data

SERVER_INFO = {"name": "hr-mcp-demo", "version": "1.0.0"}
TOOLS = [
    {"name": "get_leave_balance",
     "description": "查询员工年假余额（天）",
     "inputSchema": {"type": "object", "properties": {"emp_id": {"type": "string"}}, "required": ["emp_id"]}},
    {"name": "get_employee",
     "description": "查询员工档案",
     "inputSchema": {"type": "object", "properties": {"name_or_id": {"type": "string"}}, "required": ["name_or_id"]}},
]
IMPL = {"get_leave_balance": hr_data.get_leave_balance, "get_employee": hr_data.get_employee}


def handle(req: dict) -> dict:
    method = req.get("method")
    params = req.get("params", {}) or {}
    if method == "initialize":
        print(json.dumps({"event": "initialize", "client": params.get("clientInfo", {})}, ensure_ascii=False), file=sys.stderr)
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO}
    if method == "tools/list":
        return {"tools": TOOLS}
    # 官方 SDK 握手后还会探测资源与提示模板；教学 Server 只提供工具
    if method == "resources/list":
        return {"resources": []}
    if method == "prompts/list":
        return {"prompts": []}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments", {})
        if name not in IMPL:
            return {"isError": True, "content": [{"type": "text", "text": f"未知工具 {name}"}]}
        try:
            data = IMPL[name](**args)
            hr_data.audit("mcp_server", f"tools/call:{name}", str(args), "stdio 调用留痕")
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": False}
        except Exception as exc:
            return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    return {"error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    print(json.dumps({"event": "server_started", "tools": [t["name"] for t in TOOLS]}, ensure_ascii=False), file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        # JSON-RPC 通知（如 notifications/initialized）没有 id，绝不回响应，
        # 否则会往 stdout 写一条 id=null 的非法消息，官方 SDK 会解析报错。
        if "id" not in req or str(req.get("method", "")).startswith("notifications/"):
            continue
        result = handle(req)
        resp = {"jsonrpc": "2.0", "id": req["id"], "result": result}
        print(json.dumps(resp, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
