"""中间件与契约测试：脱敏、注入防护、用户归属强制、结构化 Schema。"""
from __future__ import annotations

from langchain_core.tools import tool

from app.agent.builder import rule_based_intent
from app.agent.middleware import (
    GUARD_REPLY,
    _accepts_user_id,
    _redact,
    get_audit_log,
)
from app.schemas import ChatRequest, PurchaseIntent, SSEEvent


def test_redact_pii():
    value = {"phone": "13812345678", "note": "mail me at a.b@test.com", "id": "11010119900101123X"}
    out = _redact(value)
    assert out["phone"] == "<phone>"
    assert out["id"] == "<id>"
    assert "<email>" in out["note"]
    assert _redact("订单 13812345678") == "订单 <phone>"


def test_accepts_user_id_detection():
    @tool
    def with_uid(order_id: str, user_id: str = "") -> str:
        """x"""
        return order_id

    @tool
    def without_uid(sku: str) -> str:
        """y"""
        return sku

    assert _accepts_user_id(with_uid) is True
    assert _accepts_user_id(without_uid) is False


def test_rule_based_intent_contract():
    cases = {
        "我的订单到哪了": "order_query",
        "这个耳机用券后多少钱": "price_calc",
        "预算 500 推荐点东西": "recommend",
        "能退货吗": "after_sale",
        "找个降噪耳机": "search_product",
        "你好呀": "other",
    }
    for text, expected in cases.items():
        intent = rule_based_intent(text)
        assert isinstance(intent, PurchaseIntent)
        assert intent.intent == expected
        assert 0.0 <= intent.confidence <= 1.0
    assert rule_based_intent("预算 500 推荐点东西").budget_max == 500.0
    assert rule_based_intent("找个降噪耳机").category == "数码"


def test_chat_request_validation():
    assert ChatRequest(message="你好").thread_id == "default"
    assert ChatRequest(message="你好", user_id="u_1001").user_id == "u_1001"
    for bad in ("", " "):
        try:
            ChatRequest(message=bad)
        except Exception:
            pass
        else:
            raise AssertionError("空消息应被拒绝")


def test_sse_event_schema():
    ev = SSEEvent(event="cards", data={"cards": [{"type": "product"}]})
    assert ev.event == "cards" and ev.data["cards"][0]["type"] == "product"
    try:
        SSEEvent(event="unknown")
    except Exception:
        pass
    else:
        raise AssertionError("非法事件类型应被拒绝")


def test_guard_reply_is_explicit():
    assert "绕过" in GUARD_REPLY
    assert isinstance(get_audit_log(), list)
