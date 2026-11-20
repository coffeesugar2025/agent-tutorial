"""第 12 章：MCP / Skill / Plugin —— 工具的"插座标准"。

跑法：python ch12_mcp/main.py

先分清三个词（面试高频）：
  · Tool        = 一个函数（你自己写、自己接进模型）
  · MCP         = 跨进程/跨语言**工具协议**（工具在别的服务里，通过 JSON-RPC 被调）
  · Skill/Plugin= 一份"能力包"（工具 + 提示词 + 使用规范 + 触发条件）

本章做两件事：
  ① 用一个**本地模拟的 MCP 服务**走完 tools/list → tools/call → 接进 create_agent
  ② 给出接真 MCP 服务（langchain-mcp-adapters）的标准写法，可直接照抄
"""

import json, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from pydantic import create_model

from common import ai_text, ai_tool, get_model, practice, section, star, title

# ============================================================
# 1) 一个"别的进程里的" MCP 服务（这里用函数模拟 stdio 上的 JSON-RPC）
# ============================================================
class MockMCPServer:
    """真实 MCP 服务一般是独立进程（stdio / HTTP），这里用同一个进程内的函数模拟它的协议。"""

    def __init__(self):
        self.name = "hr-tools"
        self._tools = {
            "get_leave_balance": {
                "description": "查询员工某年度某类假期余额",
                "inputSchema": {"type": "object", "properties": {
                    "emp_id": {"type": "string", "pattern": "^E\\d{5}$"},
                    "year": {"type": "integer"},
                    "leave_type": {"type": "string", "enum": ["年假", "调休", "病假"]}},
                    "required": ["emp_id", "year", "leave_type"]},
            },
            "get_headcount": {
                "description": "按部门查询在职人数（聚合口径）",
                "inputSchema": {"type": "object", "properties": {
                    "dept": {"type": "string"}}, "required": ["dept"]},
            },
        }

    def handle(self, method: str, params: dict) -> dict:
        """JSON-RPC 2.0 形状：{"jsonrpc":"2.0","id":1,"method":...,"params":...}"""
        if method == "tools/list":
            return {"tools": [{"name": k, **v} for k, v in self._tools.items()]}
        if method == "tools/call":
            name, args = params["name"], params["arguments"]
            if name == "get_leave_balance":
                return {"content": [{"type": "text", "text": f"{args['emp_id']} {args['year']} 年{args['leave_type']}剩余 7 天"}]}
            if name == "get_headcount":
                return {"content": [{"type": "text", "text": f"{args['dept']} 在职 3 人"}]}
            return {"content": [{"type": "text", "text": f"未知工具 {name}"}], "isError": True}
        return {"error": f"未知方法 {method}"}


server = MockMCPServer()

title("案例 1：MCP 的三步握手")
print(f"  服务名：{server.name}")
listing = server.handle("tools/list", {})
for t in listing["tools"]:
    print(f"    - {t['name']}: {t['description']}")
res = server.handle("tools/call", {"name": "get_headcount", "arguments": {"dept": "技术中心"}})
print(f"  tools/call → {res['content'][0]['text']}")
star("MCP 只规定'怎么发现工具、怎么调、错误怎么回'——它不规定工具的业务逻辑，这是它跨厂商能通用的原因")

# ============================================================
# 2) 把 MCP 工具转成 LangChain Tool（适配层）
# ============================================================
section("案例 2：适配层 —— MCP schema → LangChain Tool")


TYPE_MAP = {"string": str, "integer": int, "number": float, "boolean": bool}


def mcp_tool_to_langchain(client: MockMCPServer, spec: dict):
    """★ 适配层的全部工作：拿 JSON Schema → 造 args_schema → 包一层调用 → 结果转文本。

    生产上这一步由 langchain-mcp-adapters 的 load_mcp_tools() 完成，不用自己写；
    但你要知道它做了什么，否则工具参数对不上时无从排查。
    """
    props = spec["inputSchema"].get("properties", {})
    required = set(spec["inputSchema"].get("required", []))
    fields = {k: (TYPE_MAP.get(v.get("type", "string"), str),
                  ... if k in required else None)
              for k, v in props.items()}
    args_model = create_model(f"{spec['name']}_args", **fields)

    def _call(**kwargs) -> str:
        out = client.handle("tools/call", {"name": spec["name"], "arguments": kwargs})
        if out.get("isError"):
            raise ValueError(out["content"][0]["text"])
        return "\n".join(c.get("text", "") for c in out["content"])

    return StructuredTool.from_function(func=_call, name=spec["name"],
                                        description=spec["description"], args_schema=args_model)


TOOLS = [mcp_tool_to_langchain(server, t) for t in listing["tools"]]
model = get_model([
    ai_tool("get_headcount", {"dept": "技术中心"}, "c1"),
    ai_tool("get_leave_balance", {"emp_id": "E1001", "year": 2026, "leave_type": "年假"}, "c2"),
    ai_text("技术中心在职 3 人；张伟 2026 年年假剩 7 天。"),
])
agent = create_agent(model, tools=TOOLS, system_prompt="你是 HR 助手。查数字必须调工具，不许估算。")
out = agent.invoke({"messages": [{"role": "user", "content": "技术中心有多少人？张伟还有几天年假？"}]})
print(f"  工具往返 {sum(1 for m in out['messages'] if type(m).__name__ == 'ToolMessage')} 次")
print(f"  最终回答：{out['messages'][-1].content}")

# ============================================================
# 3) 接真 MCP 服务的标准写法（照抄即可）
# ============================================================
section("案例 3：接真 MCP 服务（需要 pip install langchain-mcp-adapters mcp）")
print("""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langgraph.prebuilt import create_react_agent

    async with MultiServerMCPClient({
        "hr":   {"command": "python", "args": ["ch12_mcp/server.py"], "transport": "stdio"},
        "fs":   {"url": "http://localhost:8000/mcp", "transport": "streamable_http"},
    }) as client:
        tools = await client.get_tools()        # ← 一个服务可能一次给十几个工具
        agent = create_react_agent(model, tools)
        await agent.ainvoke({"messages": [("user", "查一下张伟的年假")]})
""")

for line in [
    "MCP 落地的四个现实问题：",
    "① 工具太多 → 模型选错。解法：按角色分组挂载（HR 助手只挂 hr 服务），别全塞",
    "② 权限不在你这侧 → MCP 服务自己要按调用者身份鉴权，不能只靠 Agent 的 prompt",
    "③ 网络抖动 → 加超时与降级（第 15 章）",
    "④ 结果格式不统一 → 适配层统一转字符串/结构化，别让模型猜",
]:
    print(f"    {line}")

# ============================================================
# 4) Skill / Plugin 与 Tool 的区别
# ============================================================
section("案例 4：Tool / MCP / Skill 各自解决什么")
rows = [
    ("Tool", "一个函数：查余额、算天数", "模型决定'调不调、传什么'"),
    ("MCP", "一堆工具装在别的服务里", "跨语言、跨团队、跨厂商复用"),
    ("Skill", "工具 + 提示词 + 规范 + 触发条件", "把'专家怎么做这件事'固化下来"),
]
for a, b, c in rows:
    print(f"    {a:<7} {b:<26} {c}")
star("写 Skill 的关键不是写工具，是写'什么时候用、按什么顺序用、什么情况下不许用'")

practice([
    "给 MockMCPServer 加一个 create_interview 写工具，并在 Agent 侧用 allow_write 门禁控制",
    "装 langchain-mcp-adapters，把 server.py 真跑起来，对比 load_mcp_tools 与自己适配的差异",
    "写一个'离职办理' Skill：把 6 步流程、每步工具、禁止事项写成一份 md，再让 Agent 按它执行",
])
