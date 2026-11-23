"""Specialist agents built with LangChain 1.5 create_agent + production middleware."""
from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
    wrap_tool_call,
)

from ..llm.factory import get_model
from ..observability.tracer import current_trace_id, get_tracer
from .tools import load_agent_tools

PERSONAS: dict[str, str] = {
    "shopping": "你是商品导购专员。只用工具查询真实商品与库存，回答中列出商品 id、名称、价格和库存。不要编造商品。",
    "order": "你是订单专员。负责查询订单/物流和创建订单。只能处理当前用户有权访问的订单，下单前确认商品库存。",
    "support": "你是售后专员。政策问题优先检索知识库；退款申请必须给出订单号与原因。回答要简洁、可核验。",
    "general": "你是通用客服助理。用简洁中文回答，政策类问题请检索知识库。",
}

TOOL_SETS: dict[str, tuple[str, ...]] = {
    "shopping": ("search_products", "get_product", "check_inventory", "rag_search"),
    "order": ("list_orders", "get_order", "create_order", "check_inventory"),
    "support": ("rag_search", "initiate_refund", "get_order", "list_orders"),
    "general": ("rag_search", "search_products"),
}


@wrap_tool_call
async def trace_tool_call(request: Any, handler: Any) -> Any:
    """Middleware: record every tool invocation for the visual trace (async-safe)."""
    import time

    name = (request.tool_call or {}).get("name", "unknown")
    args = (request.tool_call or {}).get("args", {})
    started = time.perf_counter()
    ok = True
    try:
        result = await handler(request)
    except Exception:
        ok = False
        raise
    finally:
        latency = (time.perf_counter() - started) * 1000
        try:
            from ..api.capabilities import get_metrics
            get_metrics().record_tool_call(name, ok, latency)
        except Exception:
            pass
    get_tracer().record(current_trace_id.get(), "agent:tool", name,
                        {"args": args, "result": str(getattr(result, "content", result))[:400]})
    return result


def build_middleware() -> list[Any]:
    return [
        SummarizationMiddleware(model=get_model(), trigger=("messages", 14),
                                keep=("messages", 6)),
        ToolRetryMiddleware(max_retries=1, initial_delay=0.0, jitter=False,
                            on_failure="continue"),
        ModelCallLimitMiddleware(run_limit=6, exit_behavior="end"),
        PIIMiddleware("email", strategy="redact", apply_to_input=True),
        PIIMiddleware("phone_number", detector=r"1[3-9]\d{9}",
                      strategy="mask", apply_to_input=True),
        trace_tool_call,
    ]


async def build_specialists(user: Any, token: str | None = None) -> dict[str, Any]:
    tools = await load_agent_tools(user, token)
    model = get_model()
    agents: dict[str, Any] = {}
    for name, persona in PERSONAS.items():
        allowed = {t.name for t in tools if t.name in TOOL_SETS[name]}
        selected = [t for t in tools if t.name in allowed]
        agents[name] = create_agent(
            model=model,
            tools=selected,
            system_prompt=persona,
            middleware=build_middleware(),
            name=f"{name}_agent",
        )
    return agents
