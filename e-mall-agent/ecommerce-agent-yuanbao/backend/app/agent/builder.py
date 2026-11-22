"""LangChain 1.5 create_agent 组装入口。

用到的 1.5 核心能力：
  create_agent(model, tools, system_prompt, middleware, checkpointer, response_format)
  InMemorySaver       多轮会话记忆（LangGraph thread_id）
  ToolStrategy        结构化输出（1.5 的 response_format 策略之一）
  MCPAdapter          langchain.mcp 内置 MCP 工具发现（1.4+）
"""
from __future__ import annotations

import re
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.middleware import default_middleware
from app.agent.mock_model import ScriptedChatModel
from app.agent.prompt import SYSTEM_PROMPT
from app.config import Settings, settings
from app.schemas import PurchaseIntent

INTENT_PROMPT = """你是电商意图路由器。只输出结构化结果，不回答用户问题。
从用户话里抽取主意图、关键词、预算上限、类目，并判断是否需要调用 MCP 工具。"""


def build_model(cfg: Settings | None = None, user_id: str = "u_1001") -> Any:
    """mock 模式用脚本化模型（免 Key，真实跑 tool loop）；real 模式走 init_chat_model。"""
    cfg = cfg or settings
    if cfg.agent_mode == "real":
        kwargs: dict[str, Any] = {"temperature": 0}
        if "openai:" in cfg.model_name and cfg.openai_api_key:
            kwargs["api_key"] = cfg.openai_api_key
        if cfg.openai_base_url:
            kwargs["base_url"] = cfg.openai_base_url
        return init_chat_model(cfg.model_name, **kwargs)
    return ScriptedChatModel(user_id=user_id)


def build_agent(tools: list[Any], cfg: Settings | None = None, user_id: str = "u_1001") -> Any:
    """主导购 Agent：MCP 工具 + 中间件治理 + 会话记忆。返回 CompiledStateGraph。"""
    cfg = cfg or settings
    return create_agent(
        model=build_model(cfg, user_id),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=default_middleware(user_id=user_id, max_calls=cfg.max_tool_calls),
        checkpointer=InMemorySaver(),
        name="ecommerce-shop-agent",
    )


def build_intent_agent(cfg: Settings | None = None) -> Any:
    """结构化输出示例：response_format=ToolStrategy(PurchaseIntent)。

    LangChain 1.5 会把 schema 注册成一个工具，模型输出被校验后写入
    result["structured_response"]，前端可直接消费强类型意图。
    """
    cfg = cfg or settings
    return create_agent(
        model=build_model(cfg),
        tools=[],
        system_prompt=INTENT_PROMPT,
        response_format=ToolStrategy(PurchaseIntent),
        name="ecommerce-intent-router",
    )


def rule_based_intent(message: str) -> PurchaseIntent:
    """mock 模式下的意图兜底（不依赖 LLM），保证 /v1/intent 始终可用。"""
    q = message.strip()
    if any(k in q for k in ("订单", "物流", "快递", "签收", "单号")):
        intent, kw = "order_query", ["订单"]
    elif any(k in q for k in ("退货", "退款", "售后", "换货", "价保")):
        intent, kw = "after_sale", ["售后"]
    elif any(k in q for k in ("多少钱", "到手", "用券", "券后", "优惠")):
        intent, kw = "price_calc", ["价格"]
    elif any(k in q for k in ("推荐", "预算", "帮我挑", "想买")):
        intent, kw = "recommend", ["推荐"]
    elif any(k in q for k in ("找", "搜索", "商品", "耳机", "键盘", "风扇", "枕头")):
        intent, kw = "search_product", ["商品"]
    else:
        intent, kw = "other", []

    budget = None
    m = re.search(r"预算\s*(\d+(?:\.\d+)?)", q) or re.search(
        r"(\d+(?:\.\d+)?)\s*(?:元|块)(?:以内|以下)?", q
    )
    if m:
        budget = float(m.group(1))
    category = "数码" if any(k in q for k in ("耳机", "键盘", "风扇", "数码")) else (
        "家居" if any(k in q for k in ("枕头", "乳胶", "家居")) else None
    )
    return PurchaseIntent(
        intent=intent, keywords=kw, budget_max=budget, category=category,
        needs_tool=intent != "other", confidence=0.86 if intent != "other" else 0.4,
    )
