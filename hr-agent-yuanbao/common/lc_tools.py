"""LangChain 工具层：@tool 定义 + 可靠性包装 + 真实 MCP 桥接。

这一层把第 2、9、10、13 章的手写组件，重新用 LangChain 的 StructuredTool 表达：
  - @tool 装饰器生成带 JSON Schema 的工具，可直接 bind_tools / ToolNode
  - 每个工具内部套 retry + timeout + 降级（第 13 章护栏）
  - 写操作带幂等键（submit_leave_request）
  - 可选通过 langchain-mcp-adapters 连接第 10 章的 stdio MCP Server
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from . import hr_data
from .graph import SimpleGraph
from .reliability import CircuitBreaker, retry, with_timeout

ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER = ROOT / "demos" / "ch10_mcp_skill" / "mcp_server.py"

# 故障注入开关：由 demo 按 payload.fail_tools 设置，用于演示重试 / 降级 / 熔断
FAULT_MODE: str = "none"
_BREAKER = CircuitBreaker(threshold=2, reset_after=2.0)
CACHE = {"E1001": {"leave_balance": 5.5, "cached_at": "10 分钟前", "source": "本地缓存"}}


def set_fault(mode: str) -> None:
    global FAULT_MODE
    FAULT_MODE = mode or "none"


def _guard(name: str, fn, *, degrade_value: Any = None) -> str:
    """统一的工具护栏：超时 → 重试 → 降级；返回 JSON 字符串，错误也回灌给模型。"""
    def call():
        if FAULT_MODE == "flaky" and name == "get_leave_balance":
            call.n += 1
            if call.n <= 1:
                raise ConnectionError("HCM 连接抖动（注入故障）")
        if FAULT_MODE == "breaker" and name == "get_leave_balance":
            def boom():
                raise ConnectionError("下游连续 500（注入故障）")
            return _BREAKER.call(boom)
        return with_timeout(fn, 3.0)

    call.n = 0  # type: ignore[attr-defined]
    try:
        data = retry(call, times=2, base_delay=0.01)
        return json.dumps({"ok": True, "data": data, "tool": name}, ensure_ascii=False)
    except Exception as exc:
        hr_data.audit("tool_guard", f"degrade:{name}", "tool", str(exc))
        if degrade_value is not None:
            return json.dumps({"ok": False, "degraded": True, "data": degrade_value,
                               "error": str(exc), "tool": name,
                               "rule": "降级结果必须标注数据时效，不得伪装成实时数据"}, ensure_ascii=False)
        return json.dumps({"ok": False, "error": str(exc), "tool": name}, ensure_ascii=False)


@tool
def get_leave_balance(emp_id: str) -> str:
    """查询员工年假余额，返回 leave_balance（天）、数据来源与截止时间。"""
    return _guard("get_leave_balance", lambda: hr_data.get_leave_balance(emp_id),
                  degrade_value=CACHE.get(emp_id))


@tool
def get_attendance(emp_id: str, month: str = "2026-10") -> str:
    """查询员工某月出勤工时与加班时长。"""
    return _guard("get_attendance", lambda: hr_data.get_attendance(emp_id, month))


@tool
def get_employee(name_or_id: str) -> str:
    """按工号或姓名查询员工档案（部门、岗位、主管、入职日期）。"""
    return _guard("get_employee", lambda: hr_data.get_employee(name_or_id))


@tool
def readonly_sql(sql: str) -> str:
    """执行一条只读 SQL（Text2SQL）；服务端有白名单校验，禁止任何写操作。"""
    return _guard("readonly_sql", lambda: hr_data.readonly_sql(sql))


@tool
def org_graph_query(entity: str, relation: str = "参与项目") -> str:
    """在组织知识图谱上做多跳关系查询（等价 Text2Cypher 的极简版）。"""
    def fn():
        g = SimpleGraph(hr_data.ORG_EDGES)
        sub_text, edges = g.subgraph_text(entity, hops=2)
        related = g.find_by_relation(relation)
        return {"entity": entity, "triples": [list(e) for e in edges],
                "relation_hits": [list(e) for e in related], "subgraph_text": sub_text}
    return _guard("org_graph_query", fn)


@tool
def prepare_onboarding(candidate: str, dept: str = "产品部", position: str = "产品经理") -> str:
    """创建入职单（幂等：同一 case_id 不重复建单），返回 case_id 与初始状态。"""
    return _guard("prepare_onboarding",
                  lambda: hr_data.create_onboarding(candidate, dept, position))


@tool
def submit_leave_request(emp_id: str, start_date: str, days: float = 1.0,
                         reason: str = "事假", idem_key: str = "demo-key-001") -> str:
    """提交请假单；idem_key 是幂等键，重复提交只返回第一次结果，绝不生成两张单。"""
    return _guard("submit_leave_request",
                  lambda: hr_data.submit_leave(emp_id, start_date, start_date, days, reason, idem_key))


# ---------------- 真实 MCP 桥接（LangChain 官方适配器） ----------------

async def _mcp_call(tool_name: str, args: dict) -> Any:
    """用 langchain-mcp-adapters 拉起第 10 章的 stdio MCP Server。

    每次调用新建一次会话（教学场景够用且无跨事件循环问题）；生产应复用长连接
    + Streamable HTTP + 连接池 + 鉴权。
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    client = MultiServerMCPClient({
        "hr": {"command": sys.executable, "args": [str(MCP_SERVER)], "transport": "stdio"}
    })
    tools = await asyncio.wait_for(client.get_tools(), timeout=20)
    target = next((t for t in tools if t.name == tool_name), None)
    if target is None:
        raise RuntimeError(f"MCP Server 未提供工具 {tool_name}，可用：{[t.name for t in tools]}")
    return await asyncio.wait_for(target.ainvoke(args), timeout=20)


@tool
def mcp_hr_query(emp_id: str) -> str:
    """通过 MCP Server（独立进程 / JSON-RPC）查询年假余额，演示 LangChain ↔ MCP 真实对接。"""
    def fn():
        try:
            return asyncio.run(_mcp_call("get_leave_balance", {"emp_id": emp_id}))
        except Exception as exc:
            return json.dumps({"mcp_error": str(exc),
                               "fallback": "生产应降级到本地工具并告警"}, ensure_ascii=False)
    return _guard("mcp_hr_query", fn)


LOCAL_TOOLS = [get_leave_balance, get_attendance, get_employee, readonly_sql,
               org_graph_query, prepare_onboarding, submit_leave_request]


def build_tools(use_mcp: bool = False) -> list:
    """默认只用本地工具；use_mcp=True 时额外挂上真实的 LangChain MCP 适配器工具。"""
    tools = list(LOCAL_TOOLS)
    if use_mcp:
        try:
            import langchain_mcp_adapters  # noqa: F401
            tools.append(mcp_hr_query)
        except ImportError:
            pass   # 没装可选依赖时优雅降级，全链路照跑
    return tools
