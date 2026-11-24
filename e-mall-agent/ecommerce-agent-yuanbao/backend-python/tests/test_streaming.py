"""流式事件协议与卡片提取单测。"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage

from app.agent.runtime import extract_cards, stream_events
from app.agent.builder import build_agent
from app.agent.mcp_tools import MCPToolProvider
from app.schemas import ChatRequest


def test_extract_product_cards():
    payload = json.dumps({"ok": True, "products": [{
        "sku": "SKU-1001", "name": "星野 Pro", "brand": "星野", "category": "数码",
        "price": 899.0, "stock": 42, "in_stock": True, "rating": 4.8,
        "tags": ["降噪"], "description": "x",
    }]})
    msg = ToolMessage(content=payload, tool_call_id="c1", name="search_products")
    cards = extract_cards("search_products", msg)
    assert len(cards) == 1 and cards[0]["type"] == "product"
    assert cards[0]["price"] == 899.0


def test_extract_order_and_price_cards():
    order = json.dumps({"ok": True, "order": {
        "order_id": "EC1", "status": "运输中", "total": 799.0,
        "created_at": "2026-11-18", "logistics": {"node": "苏州"}, "items": [],
    }})
    assert extract_cards("get_order", ToolMessage(content=order, tool_call_id="c", name="get_order"))[0]["type"] == "order"

    price = json.dumps({"ok": True, "sku": "SKU-1001", "name": "星野 Pro", "quantity": 1,
                        "subtotal": 899.0, "total_discount": 100.0, "payable": 799.0,
                        "currency": "CNY", "coupons": [{"code": "FULL100", "title": "满减", "amount": 100.0}]})
    card = extract_cards("calculate_price", ToolMessage(content=price, tool_call_id="c", name="calculate_price"))[0]
    assert card["type"] == "price" and card["payable"] == 799.0


def test_extract_cards_handles_failed_tool_and_plain_text():
    assert extract_cards("x", ToolMessage(content='{"ok": false, "error": "无权限"}', tool_call_id="c", name="x")) == []
    assert extract_cards("x", ToolMessage(content="not json", tool_call_id="c", name="x")) == []


@pytest.mark.asyncio
async def test_sse_event_sequence():
    async with MCPToolProvider() as provider:
        agent = build_agent(provider.tools)
        events = [
            (event, data)
            async for event, data in stream_events(
                agent, ChatRequest(message="EC20261118001 订单到哪了", thread_id="stream-1"), "mock"
            )
        ]
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert kinds.count("tool_start") == 1 and kinds.count("tool_end") == 1
    assert "cards" in kinds
    assert sum(1 for k in kinds if k == "token") > 1  # 真正的增量分片
    joined = "".join(d["text"] for e, d in events if e == "token")
    assert "运输中" in joined
    assert events[-1][1]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_sse_card_payload_shape():
    async with MCPToolProvider() as provider:
        agent = build_agent(provider.tools)
        cards = [
            d["cards"] async for e, d in stream_events(
                agent, ChatRequest(message="帮我找降噪耳机", thread_id="stream-2"), "mock"
            ) if e == "cards"
        ]
    assert cards and all("type" in c and "sku" in c for c in cards[0])
