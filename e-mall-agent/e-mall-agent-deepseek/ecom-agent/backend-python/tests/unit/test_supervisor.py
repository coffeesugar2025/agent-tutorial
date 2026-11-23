"""Supervisor 路由单元测试：关键词兜底与模型输出归一。"""

from __future__ import annotations

import asyncio

from app.agents.state import AGENT_OPS, AGENT_SERVICE, AGENT_SHOPPING
from app.agents.supervisor import _normalize_agent, allowed_tools, keyword_route, route


def test_keyword_route_shopping():
    agent, reason = keyword_route("帮我推荐一款 5000 以内的拍照手机")
    assert agent == AGENT_SHOPPING
    assert reason


def test_keyword_route_service():
    agent, _ = keyword_route("我的订单到哪了，物流一直没更新")
    assert agent == AGENT_SERVICE


def test_keyword_route_ops():
    agent, _ = keyword_route("这个月销售额多少，环比增长怎么样")
    assert agent == AGENT_OPS


def test_keyword_route_default_is_shopping():
    agent, reason = keyword_route("你好呀")
    assert agent == AGENT_SHOPPING
    assert "默认" in reason


def test_normalize_agent_aliases():
    assert _normalize_agent("shopping") == AGENT_SHOPPING
    assert _normalize_agent("GUIDE") == AGENT_SHOPPING
    assert _normalize_agent("客服") == AGENT_SERVICE
    assert _normalize_agent("analytics") == AGENT_OPS
    assert _normalize_agent("UNKNOWN") is None
    assert _normalize_agent(None) is None
    assert _normalize_agent(123) is None


def test_allowed_tools_matches_registry():
    assert "search_products" in allowed_tools(AGENT_SHOPPING)
    assert "create_refund_request" in allowed_tools(AGENT_SERVICE)
    assert "text2sql" in allowed_tools(AGENT_OPS)
    # Supervisor 不直接持有工具，只做路由
    assert allowed_tools("SUPERVISOR") == []


def test_route_returns_valid_agent_in_mock_mode():
    """Mock 模式下模型可能返回无法解析的内容，必须回落到关键词并给出合法枚举。"""
    agent, reason = asyncio.run(route("帮我查一下订单 SO202611230001 的物流"))
    assert agent in (AGENT_SHOPPING, AGENT_SERVICE, AGENT_OPS)
    assert reason


def test_route_handles_history():
    history = [
        {"role": "user", "content": "我想买个手机"},
        {"role": "assistant", "content": "预算多少呢？"},
    ]
    agent, _ = asyncio.run(route("那它续航怎么样", history))
    assert agent in (AGENT_SHOPPING, AGENT_SERVICE, AGENT_OPS)
