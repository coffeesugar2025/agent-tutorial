"""Lightweight in-process tracing + graph metadata used by the visualisation UI."""
from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from typing import Any

current_trace_id: ContextVar[str] = ContextVar("ecom_trace_id", default="")

GRAPH_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "supervisor": {
        "title": "多智能体客服工作流",
        "nodes": [
            {"id": "context", "label": "上下文工程", "kind": "process"},
            {"id": "route", "label": "意图路由", "kind": "decision"},
            {"id": "shopping", "label": "商品导购 Agent", "kind": "agent"},
            {"id": "order", "label": "订单 Agent", "kind": "agent"},
            {"id": "support", "label": "售后 Agent", "kind": "agent"},
            {"id": "general", "label": "通用 Agent", "kind": "agent"},
            {"id": "finalize", "label": "汇总回复", "kind": "end"},
        ],
        "edges": [
            {"source": "context", "target": "route"},
            {"source": "route", "target": "shopping", "label": "商品/推荐"},
            {"source": "route", "target": "order", "label": "订单/下单"},
            {"source": "route", "target": "support", "label": "退款/政策"},
            {"source": "route", "target": "general", "label": "其他"},
            {"source": "shopping", "target": "finalize"},
            {"source": "order", "target": "finalize"},
            {"source": "support", "target": "finalize"},
            {"source": "general", "target": "finalize"},
        ],
    },
    "fulfillment": {
        "title": "订单履约工作流（含人工审批）",
        "nodes": [
            {"id": "validate", "label": "校验订单", "kind": "process"},
            {"id": "check_inventory", "label": "库存复核", "kind": "decision"},
            {"id": "risk_review", "label": "大额人工审批", "kind": "human"},
            {"id": "reserve_stock", "label": "锁定库存", "kind": "process"},
            {"id": "create_shipment", "label": "生成发货单", "kind": "process"},
            {"id": "complete", "label": "履约完成", "kind": "end"},
            {"id": "cancel", "label": "取消订单", "kind": "end"},
            {"id": "rollback", "label": "缺货回滚", "kind": "end"},
        ],
        "edges": [
            {"source": "validate", "target": "check_inventory"},
            {"source": "check_inventory", "target": "reserve_stock", "label": "库存充足"},
            {"source": "check_inventory", "target": "rollback", "label": "缺货"},
            {"source": "reserve_stock", "target": "risk_review"},
            {"source": "risk_review", "target": "create_shipment", "label": "批准"},
            {"source": "risk_review", "target": "cancel", "label": "拒绝"},
            {"source": "create_shipment", "target": "complete"},
        ],
    },
}


class TraceCollector:
    def __init__(self, max_events: int = 1000) -> None:
        self._max = max_events
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, trace_id: str, node: str, event: str,
               payload: Any = None) -> dict[str, Any]:
        entry = {"ts": time.time(), "trace_id": trace_id, "node": node,
                 "event": event, "payload": payload}
        with self._lock:
            self._events.append(entry)
            if len(self._events) > self._max:
                del self._events[: len(self._events) - self._max]
        return entry

    def query(self, limit: int = 50, trace_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if trace_id:
            items = [e for e in items if e["trace_id"] == trace_id]
        return list(reversed(items))[:limit]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_tracer: TraceCollector | None = None


def get_tracer() -> TraceCollector:
    global _tracer
    if _tracer is None:
        _tracer = TraceCollector()
    return _tracer


def describe_graphs() -> dict[str, dict[str, Any]]:
    return GRAPH_DESCRIPTIONS
