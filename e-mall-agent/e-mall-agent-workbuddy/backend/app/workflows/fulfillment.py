"""Deterministic LangGraph workflow with durable checkpoints and human approval."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..domain.repository import get_repository
from ..observability.tracer import get_tracer


class FulfillmentState(TypedDict, total=False):
    order_id: str
    customer_id: str
    steps: Annotated[list[str], operator.add]
    status: str
    amount: float
    approved: bool
    message: str


APPROVAL_THRESHOLD = 500.0


def build_fulfillment_graph() -> Any:
    tracer = get_tracer()

    def record(state: FulfillmentState, node: str, event: str, payload: Any = None) -> None:
        tracer.record(state.get("order_id", "unknown"), node, event, payload)

    def validate(state: FulfillmentState) -> dict[str, Any]:
        repo = get_repository()
        order = repo.get_order(state["order_id"])
        record(state, "validate", "check", {"exists": bool(order)})
        if not order:
            return {"status": "not_found", "message": "订单不存在", "steps": ["订单不存在"]}
        return {"status": "validated", "amount": order.total,
                "steps": [f"订单 {order.id} 校验通过，金额 ¥{order.total}"]}

    def check_inventory(state: FulfillmentState) -> dict[str, Any]:
        repo = get_repository()
        order = repo.get_order(state["order_id"])
        ok = bool(order) and all((p := repo.get_product(i.product_id)) and p.stock >= 0
                                 for i in order.items)
        record(state, "check_inventory", "result", {"ok": ok})
        return {"steps": ["库存复核通过" if ok else "库存不足"], "status": "stock_ok" if ok else "stock_missing"}

    def reserve_stock(state: FulfillmentState) -> dict[str, Any]:
        return {"steps": ["库存已锁定"], "status": "reserved"}

    def risk_review(state: FulfillmentState) -> dict[str, Any]:
        if state.get("amount", 0) >= APPROVAL_THRESHOLD and state.get("approved") is None:
            record(state, "risk_review", "interrupt", {"amount": state["amount"]})
            decision = interrupt({"kind": "approval", "order_id": state["order_id"],
                                  "amount": state["amount"],
                                  "reason": "订单金额超过人工审批阈值"})
            approved = bool(decision)
        else:
            approved = True
        return {"approved": approved, "steps": ["人工审批通过" if approved else "人工审批拒绝"]}

    def create_shipment(state: FulfillmentState) -> dict[str, Any]:
        repo = get_repository()
        order = repo.set_order_status(state["order_id"], "shipped")
        record(state, "create_shipment", "shipped", {"order": state["order_id"]})
        return {"steps": ["已生成发货单"], "status": "shipped",
                "message": f"订单 {state['order_id']} 已发货" if order else "订单不存在"}

    def complete(state: FulfillmentState) -> dict[str, Any]:
        return {"steps": ["履约完成"], "status": "completed",
                "message": f"订单 {state['order_id']} 履约完成"}

    def cancel(state: FulfillmentState) -> dict[str, Any]:
        get_repository().set_order_status(state["order_id"], "cancelled")
        return {"steps": ["订单已取消"], "status": "cancelled",
                "message": "人工审批拒绝，订单已取消"}

    def rollback(state: FulfillmentState) -> dict[str, Any]:
        get_repository().set_order_status(state["order_id"], "cancelled")
        return {"steps": ["库存回滚"], "status": "out_of_stock", "message": "库存不足，订单已取消"}

    builder = StateGraph(FulfillmentState)
    builder.add_node("validate", validate)
    builder.add_node("check_inventory", check_inventory)
    builder.add_node("reserve_stock", reserve_stock)
    builder.add_node("risk_review", risk_review)
    builder.add_node("create_shipment", create_shipment)
    builder.add_node("complete", complete)
    builder.add_node("cancel", cancel)
    builder.add_node("rollback", rollback)
    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", lambda s: "check_inventory" if s["status"] == "validated" else END)
    builder.add_conditional_edges("check_inventory", lambda s: "reserve_stock" if s["status"] == "stock_ok" else "rollback")
    builder.add_edge("reserve_stock", "risk_review")
    builder.add_conditional_edges("risk_review", lambda s: "create_shipment" if s.get("approved") else "cancel")
    builder.add_edge("create_shipment", "complete")
    builder.add_edge("complete", END)
    builder.add_edge("cancel", END)
    builder.add_edge("rollback", END)
    return builder.compile(checkpointer=InMemorySaver())


_graph: Any = None


def get_fulfillment_graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_fulfillment_graph()
    return _graph


def _serialize(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
    payload = {"thread_id": thread_id, "status": result.get("status", "unknown"),
               "message": result.get("message", ""), "steps": result.get("steps", [])}
    interruptions = result.get("__interrupt__") or ()
    if interruptions:
        item = interruptions[0]
        payload["status"] = "awaiting_approval"
        payload["interrupt"] = getattr(item, "value", item)
    return payload


async def run_fulfillment(order_id: str, customer_id: str, thread_id: str | None = None) -> dict[str, Any]:
    thread_id = thread_id or f"fulfill-{order_id}"
    config = {"configurable": {"thread_id": thread_id}}
    result = await get_fulfillment_graph().ainvoke(
        {"order_id": order_id, "customer_id": customer_id, "steps": []}, config)
    return _serialize(result, thread_id)


async def resume_fulfillment(thread_id: str, approved: bool) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    result = await get_fulfillment_graph().ainvoke(Command(resume=approved), config)
    return _serialize(result, thread_id)
