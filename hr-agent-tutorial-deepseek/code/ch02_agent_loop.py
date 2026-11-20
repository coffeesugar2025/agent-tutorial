"""第 02 章：用 LangGraph 把 Agent Loop 画出来 —— StateGraph + ToolNode + tools_condition。

显式建图：model → guard → tools → model，终止条件写进节点和条件边；用 Tracer 看每一轮，
用 TracerCallbackHandler 汇总 LLM/工具调用与 token。相比 create_agent，这一版把框架内部摊开。
运行：python code/ch02_agent_loop.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from common.data import all_policy_documents, employee
from common.lc import TracerCallbackHandler, final_text, get_chat_model, tool_names
from common.trace import Tracer

QUESTION = "我下个月想休 3 天年假，够不够？需要提前几天申请？"
SYSTEM_PROMPT = (
    "你是 HR 服务台的休假助手。规则：\n"
    "1. 先用 get_leave_balance 查余额，再用 search_policy 查制度原文。\n"
    "2. 只依据工具返回的内容回答；没有证据就说不知道，禁止编造条款。\n"
    "3. 回答要带制度编号与条款位置；不能替员工提交申请，只说明流程。\n"
    "4. 工具报错时先判断是参数问题还是权限问题，再决定重试还是解释。"
)


@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工的年假/病假余额（只读）。employee_id 是工号，如 E1001。"""
    person = employee(employee_id)
    if person is None:
        raise ValueError(f"工号 {employee_id} 不存在")
    leave = person["leave"]
    return json.dumps(
        {
            "employee_id": employee_id,
            "name": person["name"],
            "annual_remaining": leave["annual_total"] - leave["annual_used"],
            "sick_remaining": leave["sick_total"] - leave["sick_used"],
        },
        ensure_ascii=False,
    )


@tool
def search_policy(keyword: str) -> str:
    """检索生效中的 HR 制度原文（只读）。keyword 是关键词，如 申请；返回文档编号与版本。"""
    hits = []
    for doc in all_policy_documents():
        if doc["status"] != "active":
            continue  # 归档版本不参与检索，否则会答出旧口径
        for line in doc["content"].splitlines():
            if keyword in line and len(line.strip()) > 4:
                hits.append({"doc_id": doc["doc_id"], "version": doc["version"], "text": line.strip()})
    if not hits:
        raise LookupError(f"制度库里没有包含“{keyword}”的条款")
    return json.dumps(hits[:2], ensure_ascii=False)


TOOLS = [get_leave_balance, search_policy]
TOOL_NAMES = {item.name for item in TOOLS}


class AgentState(MessagesState):
    """LangGraph 的共享状态：消息用 add_messages 累加，其余字段每轮覆盖。"""

    step: int
    seen_calls: dict[str, int]
    stopped_reason: str
    unknown_tools: list[str]


@dataclass
class AgentResult:
    reply: str
    steps: int
    stopped_reason: str  # final_answer / max_steps / repeated_call / recursion_limit
    trace: Tracer
    messages: list[BaseException] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def call_key(call: dict[str, Any]) -> str:
    return call["name"] + ":" + json.dumps(call.get("args", {}), sort_keys=True, ensure_ascii=False)


def pairing_ok(messages: list[Any]) -> bool:
    """AIMessage.tool_calls 的每个 id，都必须有一条 ToolMessage 回应（LangGraph 的硬约束）。"""
    pending: set[str] = set()
    for message in messages:
        if isinstance(message, AIMessage):
            pending |= {call["id"] for call in message.tool_calls}
        elif isinstance(message, ToolMessage):
            pending.discard(message.tool_call_id)
    return not pending


def build_graph(model: BaseChatModel, max_steps: int, tracer: Tracer, callbacks: TracerCallbackHandler):
    bound = model.bind_tools(TOOLS)  # 真实模型在这里绑定工具 schema；Mock 只记录

    def model_node(state: AgentState) -> dict:
        step = state.get("step", 0)
        if step >= max_steps:  # 步数预算：框架不会自动停，必须自己写
            print(f"[stop] 达到最大步数 {max_steps}，转人工")
            return {
                "messages": [AIMessage(content="（达到最大步数，未得到最终答案，转人工处理）")],
                "stopped_reason": "max_steps",
            }
        with tracer.span(f"model[{step + 1}]") as span:
            response = bound.invoke(state["messages"])
            span.attrs["tool_calls"] = [call["name"] for call in response.tool_calls]
        names = [call["name"] for call in response.tool_calls]
        print(f"[step {step + 1}] 模型决策：tool_calls={names or '无，直接回答'}")
        return {"messages": [response], "step": step + 1}

    def guard_node(state: AgentState) -> dict:
        calls = getattr(state["messages"][-1], "tool_calls", []) or []
        if not calls:
            return {}
        seen = dict(state.get("seen_calls") or {})
        unknown = list(state.get("unknown_tools") or [])
        duplicate = False
        for call in calls:
            key = call_key(call)
            seen[key] = seen.get(key, 0) + 1
            duplicate = duplicate or seen[key] > 1
            if call["name"] not in TOOL_NAMES and call["name"] not in unknown:
                unknown.append(call["name"])
        if unknown:
            print(f"[guard] 未知工具 {unknown}，交给 ToolNode 回填错误")
        if duplicate:  # 同一工具同一参数第二次出现：补一条 ToolMessage 再终止，保证消息配对
            print("[guard] 检测到重复调用，停止并转人工")
            replies = [
                ToolMessage(content='{"ok": false, "error": "repeated_call"}', tool_call_id=call["id"], name=call["name"])
                for call in calls
            ]
            return {
                "messages": replies + [AIMessage(content="检测到重复调用，已停止并转人工。")],
                "seen_calls": seen,
                "unknown_tools": unknown,
                "stopped_reason": "repeated_call",
            }
        return {"seen_calls": seen, "unknown_tools": unknown}

    tool_node = ToolNode(TOOLS, handle_tool_errors=lambda exc: f"{type(exc).__name__}: {exc}")

    def tools_node(state: AgentState) -> dict:
        with tracer.span("tools"):
            result = tool_node.invoke(state)
        for message in result.get("messages", []):
            status = getattr(message, "status", "")
            print(f"[tools] {message.name} -> {status} {str(message.content)[:64]}")
        return result

    graph = StateGraph(AgentState)
    graph.add_node("model", model_node)
    graph.add_node("guard", guard_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "model")
    graph.add_edge("model", "guard")
    graph.add_conditional_edges("guard", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile()


def run_case(title: str, script: list[dict], max_steps: int = 6) -> AgentResult:
    print(f"\n=== {title} ===")
    tracer = Tracer("ch02-langgraph")
    callbacks = TracerCallbackHandler()
    app = build_graph(get_chat_model(script=script), max_steps, tracer, callbacks)
    initial: AgentState = {
        "messages": [HumanMessage(QUESTION)],
        "step": 0,
        "seen_calls": {},
        "stopped_reason": "",
        "unknown_tools": [],
    }
    try:
        state = app.invoke(initial, config={"recursion_limit": 3 * max_steps + 5, "callbacks": [callbacks]})
    except GraphRecursionError:  # 步数之外的第二道刹车
        return AgentResult("（递归上限触发，转人工）", max_steps, "recursion_limit", tracer, [], callbacks.summary())
    result = AgentResult(
        reply=final_text(state),
        steps=state.get("step", 0),
        stopped_reason=state.get("stopped_reason") or "final_answer",
        trace=tracer,
        messages=state["messages"],
        metrics=callbacks.summary(),
    )
    print(f"[结果] reason={result.stopped_reason} steps={result.steps} reply={result.reply[:44]}")
    return result


def agent_loop() -> None:
    normal = run_case("1. 正常流程：查余额 → 查制度 → 回答", [
        {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]},
        {"tool_calls": [{"name": "search_policy", "args": {"keyword": "申请"}}]},
        {"content": "张伟，你今年还剩 13 天年假，休 3 天够用。按 HR-LEAVE-2025（2025.1）第 2.3 条，"
         "需提前 3 个工作日提交申请；连续休假不超过 3 天由直属主管审批。"},
    ])
    print("\n=== Trace 调用树（正常流程） ===")
    normal.trace.print_tree()

    recovered = run_case("2. 工具抛异常：ToolNode 回填错误，模型改参数重试", [
        {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E9999"}}]},
        {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]},
        {"content": "工号 E9999 查不到，已按你的工号 E1001 重查：还剩 13 天年假。"},
    ])
    print("\n=== Trace 调用树（异常被 ToolNode 兜住） ===")
    recovered.trace.print_tree()

    unknown = run_case("3. 未知工具：ToolNode 返回错误，循环不崩", [
        {"tool_calls": [{"name": "submit_leave_request", "args": {"employee_id": "E1001"}}]},
        {"content": "我不能直接替你提交请假单，但可以帮你核对余额和申请时限。"},
    ])
    repeated = run_case("4. 重复调用：guard 节点第二次发现就终止", [
        {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]},
        {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]},
    ])
    maxed = run_case("5. 最大步数：max_steps=2，模型还在查资料就被截断", [
        {"tool_calls": [{"name": "search_policy", "args": {"keyword": "年假"}}]},
        {"tool_calls": [{"name": "search_policy", "args": {"keyword": "申请"}}]},
    ], max_steps=2)

    tool_messages = [m for m in normal.messages if isinstance(m, ToolMessage)]
    assert normal.stopped_reason == "final_answer" and normal.steps == 3 and len(tool_messages) == 2
    assert "13 天" in normal.reply and "3 个工作日" in tool_messages[1].content
    assert normal.metrics["llm_calls"] == 3 and normal.metrics["tool_calls"] == 2
    assert any("不存在" in str(m.content) for m in recovered.messages if isinstance(m, ToolMessage))
    assert any(
        "submit_leave_request" in str(m.content) for m in unknown.messages if isinstance(m, ToolMessage)
    ), "未知工具应该由 ToolNode 回填错误，而不是让图崩掉"
    assert repeated.stopped_reason == "repeated_call" and maxed.stopped_reason == "max_steps" and maxed.steps == 2
    assert all(pairing_ok(result.messages) for result in (normal, recovered, unknown, repeated, maxed))
    print("\n全部断言通过：LangGraph 的节点、条件边、四类终止条件与消息配对都符合预期。")

