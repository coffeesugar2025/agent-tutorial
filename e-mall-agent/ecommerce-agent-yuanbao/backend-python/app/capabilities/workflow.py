"""Workflow / State Machine：用 LangGraph StateGraph 手写显式工作流。

与 create_agent 的互补关系：
  create_agent  = 模型自主循环的「隐式」图（模型决定是否调工具）
  StateGraph    = 业务规则固定的「显式」状态机（阶段、条件分支、人工节点都写死）

本图阶段：classify → retrieve → review → respond / escalate
  classify  规则判定意图，并识别是否需要人工审批
  retrieve  按意图调用领域工具，结果写入 state
  review    事实校验（金额/库存/归属）与风险判定
  escalate  命中写操作或高风险时进入人工节点，不自动执行
  respond   汇总最终答复

状态转移是编译图里的真实边，不是 if-else 堆砌；可用 get_graph() 输出结构。
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.services import catalog


class FlowState(TypedDict, total=False):
    goal: str
    stage: str
    intent: str
    risk: str
    tool_results: list[dict[str, Any]]
    facts_ok: bool
    needs_approval: bool
    answer: str
    audit: list[str]


WRITE_WORDS = ("下单", "支付", "退款", "改地址", "取消订单", "修改订单")


def classify(state: FlowState) -> dict[str, Any]:
    q = state["goal"]
    if any(w in q for w in WRITE_WORDS):
        intent, risk, needs = "write_request", "high", True
    elif any(k in q for k in ("退货", "退款", "售后", "能退")):
        intent, risk, needs = "after_sale", "medium", False
    elif any(k in q for k in ("订单", "物流", "单号")):
        intent, risk, needs = "order_query", "low", False
    elif any(k in q for k in ("多少钱", "到手", "用券", "券后")):
        intent, risk, needs = "price_calc", "low", False
    elif any(k in q for k in ("推荐", "预算", "想买")):
        intent, risk, needs = "recommend", "low", False
    else:
        intent, risk, needs = "search_product", "low", False
    return {"stage": "classified", "intent": intent, "risk": risk,
            "needs_approval": needs,
            "audit": state.get("audit", []) + [f"classify→{intent}/{risk}"]}


def retrieve(state: FlowState) -> dict[str, Any]:
    intent = state["intent"]
    results: list[dict[str, Any]] = []
    if intent == "order_query":
        results.append({"tool": "get_order",
                        "data": catalog.get_order("EC20261118001", "u_1001")})
    elif intent == "after_sale":
        results.append({"tool": "check_after_sale_eligibility",
                        "data": catalog.check_after_sale_eligibility("EC20261105002", "u_1001")})
        results.append({"tool": "get_after_sale_policy",
                        "data": catalog.get_after_sale_policy("退货")})
    elif intent == "price_calc":
        results.append({"tool": "calculate_price",
                        "data": catalog.calculate_price("SKU-1001", 1, "FULL100")})
    elif intent == "recommend":
        results.append({"tool": "recommend_products",
                        "data": catalog.recommend_products(budget=500.0)})
    else:
        results.append({"tool": "search_products",
                        "data": catalog.search_products(keyword="耳机", limit=3)})
    return {"stage": "retrieved", "tool_results": results,
            "audit": state.get("audit", []) + [f"retrieve→{len(results)} tools"]}


def review(state: FlowState) -> dict[str, Any]:
    """事实校验：所有工具结果必须 ok=True，否则标记不合格并升级。"""
    results = state.get("tool_results", [])
    facts_ok = all(r["data"].get("ok") is True for r in results) and bool(results)
    needs = state.get("needs_approval", False) or not facts_ok
    return {"stage": "reviewed", "facts_ok": facts_ok, "needs_approval": needs,
            "audit": state.get("audit", []) + [f"review→facts_ok={facts_ok}"]}


def escalate(state: FlowState) -> dict[str, Any]:
    return {"stage": "escalated",
            "answer": "该请求涉及写操作或工具结果不可用，已转人工审批，不自动执行。",
            "audit": state.get("audit", []) + ["escalate→HITL"]}


def respond(state: FlowState) -> dict[str, Any]:
    lines = []
    for r in state.get("tool_results", []):
        d = r["data"]
        if "payable" in d:
            lines.append(f"到手 ¥{d['payable']:.2f} CNY")
        elif "order" in d:
            o = d["order"]
            lines.append(f"订单 {o['order_id']}：{o['status']}")
        elif "products" in d:
            lines.extend(f"{p['name']}（{p['sku']}）¥{p['price']:.2f}" for p in d["products"][:3])
        elif "eligible" in d:
            lines.append(f"退货资格：{'符合' if d['eligible'] else '不符合'}")
        elif "content" in d:
            lines.append(f"政策：{str(d['content'])[:100]}")
    return {"stage": "done", "answer": "已核实：" + "；".join(lines),
            "audit": state.get("audit", []) + ["respond→done"]}


def route_after_classify(state: FlowState) -> str:
    return "escalate" if state.get("needs_approval") else "retrieve"


def route_after_review(state: FlowState) -> str:
    return "escalate" if state.get("needs_approval") else "respond"


def build_workflow_graph():
    """返回编译好的 StateGraph（真实 LangGraph 图，可 get_graph() / astream）。"""
    builder = StateGraph(FlowState)
    builder.add_node("classify", classify)
    builder.add_node("retrieve", retrieve)
    builder.add_node("review", review)
    builder.add_node("escalate", escalate)
    builder.add_node("respond", respond)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_after_classify,
                                  {"retrieve": "retrieve", "escalate": "escalate"})
    builder.add_edge("retrieve", "review")
    builder.add_conditional_edges("review", route_after_review,
                                  {"respond": "respond", "escalate": "escalate"})
    builder.add_edge("respond", END)
    builder.add_edge("escalate", END)
    return builder.compile()


GRAPH = build_workflow_graph()


def run_workflow(goal: str) -> dict[str, Any]:
    state: FlowState = {"goal": goal, "tool_results": [], "audit": []}
    out = GRAPH.invoke(state)
    return {
        "goal": goal, "stage": out.get("stage"), "intent": out.get("intent"),
        "risk": out.get("risk"), "facts_ok": out.get("facts_ok"),
        "needs_approval": out.get("needs_approval"), "answer": out.get("answer", ""),
        "tools": [r["tool"] for r in out.get("tool_results", [])],
        "audit": out.get("audit", []),
        "graph_nodes": sorted(GRAPH.get_graph().nodes.keys()),
    }


def workflow_spec() -> dict[str, Any]:
    return {
        "engine": "langgraph.StateGraph (CompiledStateGraph)",
        "states": ["classify", "retrieve", "review", "respond", "escalate"],
        "edges": ["START→classify", "classify→retrieve|escalate",
                  "retrieve→review", "review→respond|escalate", "respond→END"],
        "vs_create_agent": "显式业务状态机 vs 模型自主隐式循环；可嵌套为父子图",
    }
