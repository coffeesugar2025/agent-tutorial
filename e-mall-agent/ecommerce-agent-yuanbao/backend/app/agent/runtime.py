"""Agent 运行层：把 LangGraph 事件流翻译成前端可消费的 SSE 协议。

SSE 事件（POST /v1/chat）：
  meta       会话与模型元信息
  token      回答文本增量
  tool_start 工具开始（名称 + 入参）
  tool_end   工具结束（结果摘要）
  cards      从工具结果中提取的结构化卡片（商品 / 订单 / 价格 / 政策）
  error      异常
  done       结束（耗时、工具调用次数）
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessageChunk, ToolMessage

from app.schemas import ChatRequest, ChatSyncResponse


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                out.append(str(b.get("text", "")))
        return "".join(out)
    return str(content or "")


def _parse(content: Any) -> dict[str, Any] | None:
    raw = _text(content)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def extract_cards(tool_name: str, output: Any) -> list[dict[str, Any]]:
    """把 MCP 工具返回的结构化数据转成前端卡片（不依赖 LLM 复述，避免失真）。"""
    content = getattr(output, "content", output)
    data = _parse(content)
    if not data or not data.get("ok"):
        return []
    cards: list[dict[str, Any]] = []

    for p in data.get("products", [])[:3]:
        cards.append({
            "type": "product", "sku": p.get("sku"), "title": p.get("name"),
            "subtitle": f"{p.get('brand', '')} · {p.get('category', '')}",
            "price": p.get("price"), "stock": p.get("stock"),
            "in_stock": p.get("in_stock"), "rating": p.get("rating"),
            "tags": p.get("tags", []), "description": p.get("description", ""),
        })
    for o in ([data["order"]] if "order" in data else data.get("orders", [])[:3]):
        cards.append({
            "type": "order", "order_id": o.get("order_id"), "status": o.get("status"),
            "total": o.get("total"), "created_at": o.get("created_at"),
            "node": (o.get("logistics") or {}).get("node", ""),
            "items": o.get("items", []),
        })
    if "payable" in data:
        cards.append({
            "type": "price", "sku": data.get("sku"), "title": data.get("name"),
            "subtotal": data.get("subtotal"), "discount": data.get("total_discount"),
            "payable": data.get("payable"), "currency": data.get("currency", "CNY"),
            "coupons": data.get("coupons", []), "quantity": data.get("quantity"),
        })
    if "coupons" in data and "payable" not in data:
        for c in data["coupons"][:4]:
            cards.append({"type": "coupon", "code": c.get("code"), "title": c.get("title"),
                          "threshold": c.get("threshold"), "value": c.get("value")})
    if data.get("content"):
        cards.append({"type": "policy", "topic": data.get("topic"), "content": data["content"]})
    if "eligible" in data:
        cards.append({"type": "after_sale", "eligible": data["eligible"],
                      "reason": data.get("reason"), "days_left": data.get("days_left")})
    if "stock" in data and not cards:
        cards.append({"type": "inventory", "sku": data.get("sku"),
                      "title": data.get("name"), "stock": data.get("stock"),
                      "in_stock": data.get("in_stock")})
    return cards


def _config_for(req: ChatRequest) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": req.thread_id},
        "metadata": {"user_id": req.user_id, "thread_id": req.thread_id},
        "recursion_limit": 24,
    }


def _input_for(req: ChatRequest) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": req.message}]}


async def stream_events(agent: Any, req: ChatRequest, model_desc: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    started = time.perf_counter()
    tool_count = 0
    yield "meta", {"thread_id": req.thread_id, "user_id": req.user_id, "model": model_desc}
    try:
        async for ev in agent.astream_events(_input_for(req), config=_config_for(req), version="v2"):
            kind = ev.get("event", "")
            name = ev.get("name", "")
            data = ev.get("data", {})

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if isinstance(chunk, AIMessageChunk):
                    delta = _text(chunk.content)
                    if delta:
                        yield "token", {"text": delta}

            elif kind == "on_tool_start":
                tool_count += 1
                yield "tool_start", {
                    "name": name,
                    "args": data.get("input", {}),
                    "index": tool_count,
                }

            elif kind == "on_tool_end":
                output = data.get("output")
                content = getattr(output, "content", output)
                yield "tool_end", {
                    "name": name,
                    "summary": _text(content)[:400],
                }
                cards = extract_cards(name, output)
                if cards:
                    yield "cards", {"cards": cards}

        yield "done", {
            "thread_id": req.thread_id,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "tool_calls": tool_count,
        }
    except Exception as exc:
        yield "error", {"message": f"{type(exc).__name__}: {exc}"}


async def run_sync(agent: Any, req: ChatRequest) -> ChatSyncResponse:
    started = time.perf_counter()
    result = await agent.ainvoke(_input_for(req), config=_config_for(req))
    messages = result.get("messages", [])

    answer = ""
    for m in reversed(messages):
        if isinstance(m, AIMessageChunk) or m.__class__.__name__ == "AIMessage":
            answer = _text(getattr(m, "content", ""))
            if answer:
                break

    traces: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            traces.append({"name": m.name or "", "summary": _text(m.content)[:400]})
            cards.extend(extract_cards(m.name or "", m))

    return ChatSyncResponse(
        thread_id=req.thread_id,
        answer=answer or "未能生成回复，请重试。",
        tool_traces=traces,
        cards=cards,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
