"""Multi-agent supervisor: context -> intent routing -> specialist -> final answer."""
from __future__ import annotations

import operator
import uuid
from typing import Annotated, Any, AsyncIterator, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from ..context.engine import ContextEngine
from ..domain.models import User
from ..llm.factory import RuleBasedChatModel
from ..mcp.tools import ALL_TOOL_FUNCTIONS
from ..observability.tracer import current_trace_id, get_tracer
from ..rag.pipeline import get_rag_pipeline
from ..security.rbac import filter_tools
from .specialists import build_specialists
from .tools import local_tools

PERSONA = (
    "你是电商平台的智能客服编排器。必须只依据工具返回与知识库事实回答，不得虚构订单或商品。"
    "遇到权限不足时明确告知用户。回答使用简洁中文。"
)


class SupervisorState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], operator.add]
    history: list[BaseMessage]
    user_input: str
    user_id: str
    role: str
    route: str
    trace_id: str
    final_answer: str
    context_snapshot: dict[str, Any]


def classify_route(text: str) -> str:
    """Deterministic intent router; swap for an LLM router in production."""
    t = (text or "").lower()
    tool = RuleBasedChatModel.pick_tool(t)
    if tool in ("search_products", "get_product", "check_inventory"):
        return "shopping"
    if tool in ("create_order", "list_orders", "get_order"):
        return "order"
    if "退款" in t or "退货" in t or "售后" in t or "投诉" in t or "换货" in t:
        return "support"
    if tool == "rag_search":
        return "support" if any(k in t for k in
                                ("政策", "保修", "配送", "发票", "优惠券", "运费", "规则")) else "general"
    return "general"


class ConversationStore:
    """Short-term conversation memory keyed by thread_id (replace with Redis in prod)."""

    def __init__(self, max_turns: int = 12) -> None:
        self.max_turns = max_turns
        self._history: dict[str, list[BaseMessage]] = {}

    def get(self, thread_id: str) -> list[BaseMessage]:
        return list(self._history.get(thread_id, []))

    def append(self, thread_id: str, user_msg: str, ai_msg: str) -> None:
        turns = self._history.setdefault(thread_id, [])
        turns.extend([HumanMessage(content=user_msg), AIMessage(content=ai_msg)])
        self._history[thread_id] = turns[-self.max_turns * 2:]

    def clear(self, thread_id: str | None = None) -> None:
        if thread_id:
            self._history.pop(thread_id, None)
        else:
            self._history.clear()


_conversation_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store


async def build_supervisor(user: User, token: str | None = None) -> Any:
    specialists = await build_specialists(user, token)
    engine = ContextEngine()
    tracer = get_tracer()

    def context_node(state: SupervisorState) -> dict[str, Any]:
        current_user = User(id=state["user_id"], name=user.name, role=state["role"])
        docs = get_rag_pipeline().retrieve(state["user_input"])
        catalog = filter_tools(local_tools(), current_user)
        messages, snapshot = engine.build(
            persona=PERSONA, user=current_user, retrieved_docs=docs,
            tools=catalog, history=state.get("history", []), user_input=state["user_input"],
        )
        tracer.record(state["trace_id"], "context", "context_built", snapshot.as_dict())
        return {"messages": messages, "context_snapshot": snapshot.as_dict()}

    def route_node(state: SupervisorState) -> dict[str, Any]:
        route = classify_route(state["user_input"])
        tracer.record(state["trace_id"], "route", "intent", {"route": route})
        return {"route": route}

    def make_agent_node(name: str, agent: Any):
        async def node(state: SupervisorState) -> dict[str, Any]:
            marker = current_trace_id.set(state["trace_id"])
            tracer.record(state["trace_id"], name, "agent_start")
            try:
                result = await agent.ainvoke({"messages": state["messages"]})
                messages = result.get("messages", [])
                for message in messages:
                    if isinstance(message, ToolMessage):
                        tracer.record(state["trace_id"], name, "tool_result",
                                      {"tool": message.name, "content": str(message.content)[:300]})
                return {"messages": messages}
            finally:
                current_trace_id.reset(marker)

        node.__name__ = name
        return node

    def finalize_node(state: SupervisorState) -> dict[str, Any]:
        answer = ""
        for message in reversed(state.get("messages", [])):
            if isinstance(message, AIMessage) and message.content and not message.tool_calls:
                answer = str(message.content)
                break
        answer = answer or "已处理完成，但未能生成具体内容。"
        tracer.record(state["trace_id"], "finalize", "answer", {"length": len(answer)})
        return {"final_answer": answer}

    builder = StateGraph(SupervisorState)
    builder.add_node("context", context_node)
    builder.add_node("route", route_node)
    for name, agent in specialists.items():
        builder.add_node(name, make_agent_node(name, agent))
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "context")
    builder.add_edge("context", "route")
    builder.add_conditional_edges("route", lambda s: s["route"],
                                  {name: name for name in specialists})
    for name in specialists:
        builder.add_edge(name, "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=InMemorySaver())


def _input_state(user_input: str, user: User, trace_id: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=user_input)],
        "history": get_conversation_store().get(trace_id),
        "user_input": user_input,
        "user_id": user.id,
        "role": user.role,
        "trace_id": trace_id,
    }


async def run_agent(user_input: str, user: User, thread_id: str = "default",
                    token: str | None = None) -> dict[str, Any]:
    import time
    started = time.perf_counter()
    graph = await build_supervisor(user, token)
    config = {"configurable": {"thread_id": f"{thread_id}-{uuid.uuid4().hex[:8]}"}}
    result = await graph.ainvoke(_input_state(user_input, user, thread_id), config)
    answer = result.get("final_answer", "")
    get_conversation_store().append(thread_id, user_input, answer)
    route = result.get("route", "general")
    try:
        from ..api.capabilities import get_metrics
        get_metrics().record_agent_run(
            route=route, ok=bool(answer),
            latency_ms=(time.perf_counter() - started) * 1000,
            tokens=len(answer),
            tools_used=[m.name for m in result.get("messages", [])
                        if isinstance(m, ToolMessage) and m.name],
        )
    except Exception:
        pass
    return {
        "answer": answer,
        "route": route,
        "trace_id": thread_id,
        "context": result.get("context_snapshot", {}),
        "messages": result.get("messages", []),
    }


async def stream_agent(user_input: str, user: User, thread_id: str = "default",
                       token: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """SSE-friendly event stream: node transitions, tool calls, then answer tokens."""
    graph = await build_supervisor(user, token)
    config = {"configurable": {"thread_id": f"{thread_id}-{uuid.uuid4().hex[:8]}"}}
    async for update in graph.astream(_input_state(user_input, user, thread_id),
                                      config=config, stream_mode="updates"):
        for node, payload in update.items():
            yield {"event": "node", "node": node}
            if not isinstance(payload, dict):
                continue
            if "context_snapshot" in payload:
                yield {"event": "context", "data": payload["context_snapshot"]}
            if "route" in payload:
                yield {"event": "route", "data": payload["route"]}
            for message in payload.get("messages", []):
                if isinstance(message, ToolMessage):
                    yield {"event": "tool", "data": {"name": message.name,
                                                     "content": str(message.content)[:600]}}
            if "final_answer" in payload:
                answer = payload["final_answer"]
                for i in range(0, len(answer), 12):
                    yield {"event": "token", "data": answer[i:i + 12]}
                yield {"event": "done", "data": answer}

    # final_answer may be absent from partial stream updates depending on graph version
    state = await graph.aget_state(config)
    answer = (state.values or {}).get("final_answer", "")
    if answer:
        get_conversation_store().append(thread_id, user_input, answer)
