"""工具注册表：按 agent 分配工具集，并提供 LangChain / OpenAI schema 两种导出。"""

from __future__ import annotations

import json
from typing import Any

from app.tools.analytics_tools import RUN_PYTHON, TEXT2SQL
from app.tools.base import ApprovalRequired, ToolContext, ToolExecutor, ToolSpec, executor
from app.tools.human_tools import ESCALATE_TO_HUMAN
from app.tools.knowledge_tools import SEARCH_KNOWLEDGE
from app.tools.order_tools import (
    CHECK_REFUND_ELIGIBILITY,
    GET_LOGISTICS,
    GET_ORDER,
    LIST_ORDERS,
)
from app.tools.product_tools import COMPARE_PRODUCTS, GET_PRODUCT_DETAIL, SEARCH_PRODUCTS
from app.tools.refund_tools import CREATE_REFUND_REQUEST

# 与 docs/00 §5 的工具集定义严格一致
AGENT_TOOL_NAMES: dict[str, list[str]] = {
    "SUPERVISOR": [],
    "SHOPPING": ["search_products", "get_product_detail", "compare_products", "search_knowledge"],
    "SERVICE": [
        "get_order",
        "list_orders",
        "get_logistics",
        "check_refund_eligibility",
        "create_refund_request",
        "search_knowledge",
        "escalate_to_human",
    ],
    "OPS": ["text2sql", "run_python", "search_knowledge"],
}

_ALL_SPECS: list[ToolSpec] = [
    SEARCH_PRODUCTS,
    GET_PRODUCT_DETAIL,
    COMPARE_PRODUCTS,
    GET_ORDER,
    LIST_ORDERS,
    GET_LOGISTICS,
    CHECK_REFUND_ELIGIBILITY,
    CREATE_REFUND_REQUEST,
    SEARCH_KNOWLEDGE,
    TEXT2SQL,
    RUN_PYTHON,
    ESCALATE_TO_HUMAN,
]

TOOL_SPECS: dict[str, ToolSpec] = {spec.name: spec for spec in _ALL_SPECS}


def get_spec(name: str) -> ToolSpec:
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise KeyError(f"未注册的工具: {name}")
    return spec


def tools_for(agent_type: str) -> list[ToolSpec]:
    """按 agent 返回工具定义（顺序与 docs/00 一致）。"""
    names = AGENT_TOOL_NAMES.get(agent_type.upper(), [])
    return [TOOL_SPECS[name] for name in names if name in TOOL_SPECS]


def openai_tools_for(agent_type: str) -> list[dict[str, Any]]:
    """bind_tools 用的 OpenAI function schema 列表。"""
    return [spec.to_openai_tool() for spec in tools_for(agent_type)]


def describe_tools(agent_type: str | None = None) -> list[dict[str, Any]]:
    """MCP 描述 / 运维排查用：工具清单与风险级别。"""
    specs = tools_for(agent_type) if agent_type else list(TOOL_SPECS.values())
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "risk": spec.risk.value,
            "timeoutSeconds": spec.timeout_seconds,
            "retryable": spec.risk.value == "READ" and spec.max_retries > 0,
            "parameters": spec.to_openai_tool()["function"]["parameters"],
        }
        for spec in specs
    ]


async def prepare_langchain_tools(
    agent_type: str,
    ctx: ToolContext,
    tool_executor: ToolExecutor | None = None,
) -> list[Any]:
    """导出为 LangChain ``StructuredTool``（供 create_agent 图引擎使用）。

    审批中断在工具内部被转成标记 JSON（``approvalRequired``），由引擎在事件流里识别。
    """
    from langchain_core.tools import StructuredTool

    runner = tool_executor or executor
    tools: list[Any] = []
    for spec in tools_for(agent_type):

        async def _run(_spec: ToolSpec = spec, **kwargs: Any) -> str:
            try:
                result = await runner.execute(_spec, kwargs, ctx)
            except ApprovalRequired as exc:
                return json.dumps(
                    {
                        "approvalRequired": True,
                        "tool": exc.tool,
                        "actionType": exc.action_type,
                        "title": exc.title,
                        "detail": exc.detail,
                    },
                    ensure_ascii=False,
                )
            return result.to_content()

        tools.append(
            StructuredTool.from_function(
                coroutine=_run,
                name=spec.name,
                description=spec.description,
                args_schema=spec.args_model,
            )
        )
    return tools


__all__ = [
    "AGENT_TOOL_NAMES",
    "TOOL_SPECS",
    "describe_tools",
    "get_spec",
    "openai_tools_for",
    "prepare_langchain_tools",
    "tools_for",
]
