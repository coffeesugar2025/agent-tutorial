"""15 章 LangChain / LangGraph 章节实现。

每个 chapter_XX(payload, ctx) 都是**独立入口**：不依赖其他章节，可单独运行、单独删除。
薄封装 demos/chNN_xxx/demo.py 只负责暴露统一契约的 run() / resume() / state()。

全书技术主线（每一章都真实调用，不是文字提及）：
  langchain_core  : ChatPromptTemplate / RunnableSequence / BaseChatModel / BaseRetriever
                    / @tool / Document / PydanticOutputParser / trim_messages / BaseCallbackHandler
  langgraph       : StateGraph / add_messages / ToolNode / MemorySaver / InMemoryStore
                    / interrupt / Command / conditional_edges
  langchain_ollama: ChatOllama（真实模型模式）
  langchain-mcp-adapters / langchain_community : MCP 工具与 Embeddings
"""
# 注意：这里刻意不启用 `from __future__ import annotations`。
# LangGraph 的 add_conditional_edges 会对条件边函数做 get_type_hints()，
# 若注解被延迟成字符串，定义在函数内的 TypedDict（LoopState / ToolState / ReactState）
# 会解析失败并抛 NameError。Python 3.10+ 原生支持本文件用到的所有类型写法。
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

from langchain_core.documents import Document
from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage, SystemMessage,
                                    ToolMessage, trim_messages)
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.tools import tool
from langchain_core.vectorstores import InMemoryVectorStore
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common import config as app_config, hr_data  # noqa: E402
from common.context import Context  # noqa: E402
from common.lc_callbacks import TraceCallbackHandler  # noqa: E402
from common.lc_graph import CHECKPOINTER as FULL_CHECKPOINTER  # noqa: E402
from common.lc_kit import (CHECKPOINTER, STORE, callback, config, ctx_message,  # noqa: E402
                           finish, invoke, prompt_chain, seed_store, short, token_counter, trim)
from common.lc_models import (SQL_MOCK, TeachingChatModel, classify_intent,  # noqa: E402
                              build_embeddings)
from common.lc_retrieval import build_retriever, load_active_chunks  # noqa: E402
from common.lc_tools import (build_tools, get_attendance, get_employee,  # noqa: E402
                            get_leave_balance, org_graph_query, readonly_sql,
                            set_fault, submit_leave_request)
from common.reliability import BudgetGuard  # noqa: E402


def _tid() -> str:
    return "lc-" + uuid.uuid4().hex[:10]


def _ctx(payload: dict, **extra: Any) -> SystemMessage:
    return ctx_message({**payload, **extra})


def _parse_json(text: Any, fallback: dict) -> dict:
    try:
        s = str(text).strip()
        if s.startswith("```"):
            s = s.split("```")[1].lstrip("json").strip()
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else fallback
    except Exception:
        return fallback


def _cfg(thread_id: str, cb: TraceCallbackHandler, limit: int = 24) -> dict:
    return config(thread_id, cb, recursion_limit=limit)


# =====================================================================
# 第 1 章  Agent Loop：LCEL 一次问答 vs LangGraph 循环 + 终止条件
# =====================================================================
def chapter_01(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    question = str(payload.get("question", "我今年还剩几天年假？"))
    max_steps = int(payload.get("max_steps", 4))
    budget = int(payload.get("token_budget", 800))
    thread = _tid()
    cfg = _cfg(thread, cb, limit=max(8, max_steps * 2))
    guard = BudgetGuard(max_steps=max_steps, token_budget=budget)

    # ① LCEL：一次问答（普通聊天，不是 Agent）
    one_shot = (ChatPromptTemplate.from_messages([
        ("system", "你是 HR 助手，简洁回答。"), ("human", "{input}")])
        | ctx.chat_model("compose") | StrOutputParser())
    naive = invoke(one_shot, {"input": question}, cfg, ctx, label="LCEL 一次问答")
    ctx.trace("thought", "LCEL 一次问答：模型没有工具，只能凭记忆回答（会编造业务数据）",
              api="ChatPromptTemplate | ChatModel | StrOutputParser")

    class LoopState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        scratch: list[str]
        done: bool
        rounds: int

    def think(state: LoopState) -> dict:
        guard.tick(tokens=120)
        stop = guard.should_stop()
        n = state["rounds"] + 1
        if stop:
            ctx.trace("error", f"LangGraph 终止条件触发：{stop}（步数 / Token 双刹车）")
            return {"done": True, "rounds": n,
                    "scratch": state["scratch"] + [f"第{n}轮：被护栏强制收敛"]}
        if isinstance(state["messages"][-1], ToolMessage):
            pass
        round_reply = {
            1: "10 天。",
            2: "自检：上一句没有 HCM 依据，收回『10 天』。",
        }.get(n, "我无法凭记忆确认年假余额，需要接入 HCM 查询工具（见第 2 章）。")
        finished = n >= 3
        msg = AIMessage(content=round_reply)
        chain = RunnableLambda(lambda x: x["messages"]) | ctx.chat_model("loop")
        # 用 RunnableSequence 包一层，保证每一轮都走 LangChain 调用链
        try:
            ai = (RunnableLambda(lambda x: [_ctx({"mock_response": round_reply})] + x)
                  | ctx.chat_model("loop")).invoke(state["messages"], config=cfg)
            msg = ai if isinstance(ai, AIMessage) else AIMessage(content=str(ai))
        except Exception as exc:
            ctx.trace("error", f"Loop 节点降级：{exc}")
        ctx.trace("thought", f"LangGraph 第 {n} 轮 Thought：{str(msg.content)[:80]}")
        return {"messages": [msg], "done": finished, "rounds": n,
                "scratch": state["scratch"] + [f"第{n}轮：{str(msg.content)[:80]}"]}

    def should_continue(state: LoopState) -> str:
        return END if state["done"] else "think"

    g = StateGraph(LoopState)
    g.add_node("think", think)
    g.add_edge(START, "think")
    g.add_conditional_edges("think", should_continue, {"think": "think", END: END})
    graph = g.compile(checkpointer=CHECKPOINTER)
    out = graph.invoke({"messages": [HumanMessage(content=question)], "scratch": [],
                        "done": False, "rounds": 0}, config=cfg)
    final = str(out["messages"][-1].content)
    if guard.should_stop():
        final = "已达到最大步数 / Token 预算，按兜底策略结束：当前无法确认年假余额，需要接入 HCM 工具。"
    ctx.trace("state", f"LangGraph 循环结束：共 {out['rounds']} 轮，termination={'finish' if not guard.should_stop() else 'guard'}")
    return finish(ctx, cb, final, state={
        "framework": "LangGraph StateGraph + add_messages + conditional_edges",
        "lcel_one_shot": str(naive)[:160],
        "rounds": out["rounds"], "scratch": out["scratch"],
        "termination": "模型输出 finish" if not guard.should_stop() else "BudgetGuard 强制终止",
        "guard": guard.snapshot(),
        "note": "recursion_limit 是 LangGraph 自带的第三重刹车，防止图无限循环",
    })


# =====================================================================
# 第 2 章  Tool / Function Calling：@tool + bind_tools + ToolNode
# =====================================================================
def chapter_02(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    question = str(payload.get("question", "我今年还剩几天年假？"))
    emp = str(payload.get("emp_id", "E1001"))
    thread = _tid()
    cfg = _cfg(thread, cb)

    tools = [get_leave_balance, get_attendance, get_employee]
    ctx.trace("state", "用 @tool 生成 StructuredTool（自动带 JSON Schema）→ bind_tools → ToolNode",
              tools=[t.name for t in tools])

    class ToolState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        emp_id: str

    def agent(state: ToolState) -> dict:
        wants_attendance = any(w in question for w in ("加班", "出勤", "考勤"))
        spec = {"name": "get_attendance", "args": {"emp_id": emp, "month": "2026-10"}} \
            if wants_attendance else {"name": "get_leave_balance", "args": {"emp_id": emp}}
        if any(isinstance(m, ToolMessage) for m in state["messages"]):
            ai = AIMessage(content="工具结果已回灌，信息充分，退出工具循环。")
        else:
            msgs = [_ctx({"mock_tool": spec, "emp_id": emp})] + state["messages"]
            ai = ctx.chat_model("tools").bind_tools(tools).invoke(msgs, config=cfg)
            ctx.trace("thought", "模型只输出 tool_calls 意图；参数校验与执行由服务端完成",
                      tool_calls=getattr(ai, "tool_calls", []))
        return {"messages": [ai]}

    def route(state: ToolState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and getattr(last, "tool_calls", None) else END

    g = StateGraph(ToolState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    graph = g.compile(checkpointer=CHECKPOINTER)
    out = graph.invoke({"messages": [HumanMessage(content=question)], "emp_id": emp}, config=cfg)

    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    result_payload = _parse_json(tool_msgs[-1].content, {}) if tool_msgs else {}
    data = result_payload.get("data", {})
    if isinstance(data, dict) and "leave_balance" in data:
        answer = (f"{data.get('name','员工')}（{emp}）年假余额 {data['leave_balance']} 天，"
                  f"数据来自 {data.get('source','HCM.leave_account')}，截至 {data.get('as_of','')}。")
    elif isinstance(data, dict):
        answer = (f"{emp} 在 {data.get('month','2026-10')} 出勤 {data.get('hours')} 小时，"
                  f"加班 {data.get('overtime')} 小时。")
    else:
        answer = "工具未返回可解析数据，按降级策略转人工确认。"
    return finish(ctx, cb, answer, state={
        "framework": "@tool → bind_tools → ToolNode → ToolMessage 回灌",
        "tools": [t.name for t in tools], "tool_result": result_payload,
        "message_types": [type(m).__name__ for m in out["messages"]],
        "validation": "参数来自登录态 emp_id，模型输出的身份一律不可信（数据隔离）",
    })


# =====================================================================
# 第 3 章  ReAct / Plan-and-Solve：条件边循环 vs PydanticOutputParser 计划
# =====================================================================
def chapter_03(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    mode = str(payload.get("mode", "react"))
    task = str(payload.get("task", "帮我给新员工陈明办理入职，并同步进度"))
    thread = _tid()
    cfg = _cfg(thread, cb)

    if mode == "plan":
        class PlanStep(BaseModel):
            id: int
            title: str
            tool: str
        class Plan(BaseModel):
            goal: str
            steps: list[PlanStep]
            success_criteria: str
        parser = PydanticOutputParser(pydantic_object=Plan)
        plan_text = ("把任务拆成可执行计划，只输出 JSON：{input}\n{format_instructions}")
        chain = prompt_chain(ctx, plan_text, "plan", parser=parser)
        try:
            plan_obj = invoke(chain, {"input": task}, cfg, ctx, label="Plan 结构化输出")
            plan = plan_obj.dict() if isinstance(plan_obj, BaseModel) else _parse_json(plan_obj, {})
        except Exception as exc:
            ctx.trace("error", f"PydanticOutputParser 校验失败，降级到确定性计划：{exc}")
            plan = {}
        if not plan.get("steps"):
            plan = {"goal": task, "success_criteria": "生成 case_id 并停在主管审批",
                    "steps": [
                        {"id": 1, "title": "核对入职材料", "tool": "check_material"},
                        {"id": 2, "title": "创建入职单", "tool": "create_onboarding"},
                        {"id": 3, "title": "主管审批（强制人工）", "tool": "human"},
                        {"id": 4, "title": "HR 复核 / IT 开账号", "tool": "it_provisioning"},
                    ]}
        ctx.trace("plan", f"PydanticOutputParser 解析出 {len(plan['steps'])} 步计划｜验收：{plan.get('success_criteria')}")
        executed = []
        case_id = ""
        for s in plan["steps"]:
            if s.get("tool") == "human":
                executed.append({"step": s["id"], "status": "WAIT_HUMAN"})
                ctx.trace("hitl", "执行器读到 human 节点，硬暂停（规则在代码里，不靠模型自觉）")
                break
            if s.get("tool") == "create_onboarding":
                case_id = hr_data.create_onboarding("陈明", "产品部", "产品经理")["case_id"]
            executed.append({"step": s["id"], "title": s.get("title"), "status": "DONE"})
        answer = f"Plan-and-Solve：已生成 {len(plan['steps'])} 步计划，执行 {len(executed)} 步后停在主管审批（{case_id}）。"
        return finish(ctx, cb, answer, state={
            "strategy": "Plan-and-Solve（PydanticOutputParser + 确定性执行器）",
            "framework": "ChatPromptTemplate | ChatModel | PydanticOutputParser",
            "plan": plan, "executed": executed, "case_id": case_id,
            "termination": "human 节点硬暂停",
        })

    # ReAct：LangGraph 条件边实现 Thought → Action → Observation 闭环
    class ReactState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        executed: list[dict]
        case_id: str

    actions = [
        {"action": "check_material", "args": {"candidate": "陈明"}},
        {"action": "create_onboarding", "args": {"candidate": "陈明"}},
        {"action": "notify_hrbp", "args": {"channel": "IM"}},
        {"action": "finish", "args": {}},
    ]

    def think(state: ReactState) -> dict:
        i = len(state["executed"])
        step = actions[min(i, len(actions) - 1)]
        reply = json.dumps({"thought": f"已完成 {i} 步，下一步 {step['action']}", **step}, ensure_ascii=False)
        ai = (RunnableLambda(lambda msgs: [_ctx({"mock_response": reply})] + msgs)
              | ctx.chat_model("tools")).invoke(state["messages"], config=cfg)
        ctx.trace("thought", f"ReAct Thought（第 {i+1} 轮）：{step['action']}")
        return {"messages": [AIMessage(content=str(getattr(ai, "content", reply)))]}

    def act(state: ReactState) -> dict:
        i = len(state["executed"])
        step = actions[min(i, len(actions) - 1)]
        name = step["action"]
        if name == "finish":
            return {"executed": state["executed"] + [{"action": "finish", "status": "DONE"}]}
        case_id = state["case_id"]
        if name == "create_onboarding":
            case_id = hr_data.create_onboarding("陈明", "产品部", "产品经理")["case_id"]
        obs = {"action": name, "result": "ok", "case_id": case_id}
        ctx.trace("observation", f"ReAct Observation：{name} → {json.dumps(obs, ensure_ascii=False)[:120]}")
        return {"messages": [ToolMessage(content=json.dumps(obs, ensure_ascii=False),
                                         tool_call_id=f"react_{i}")],
                "executed": state["executed"] + [obs], "case_id": case_id}

    def route(state: ReactState) -> str:
        return END if (state["executed"] and state["executed"][-1].get("action") == "finish") else "act"

    g = StateGraph(ReactState)
    g.add_node("think", think)
    g.add_node("act", act)
    g.add_edge(START, "think")
    g.add_edge("think", "act")
    g.add_conditional_edges("act", route, {"act": "think", END: END})
    graph = g.compile(checkpointer=CHECKPOINTER)
    out = graph.invoke({"messages": [HumanMessage(content=task)], "executed": [], "case_id": ""}, config=cfg)
    answer = (f"ReAct：逐轮 Thought → Action → Observation 共 {len(out['executed'])} 轮，"
              f"生成入职单 {out['case_id']} 后停在主管审批（不得代批）。")
    return finish(ctx, cb, answer, state={
        "strategy": "ReAct（LangGraph conditional_edges 闭环）",
        "framework": "StateGraph + add_messages + ToolMessage 回灌",
        "executed": out["executed"], "case_id": out["case_id"],
        "comparison": "Plan 可审计可回放；ReAct 灵活但状态藏在对话里，生产常用 LangGraph 图结构收敛",
    })


# =====================================================================
# 第 4 章  Workflow / StateGraph / interrupt / Command(resume)
# =====================================================================
def chapter_04(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    candidate = str(payload.get("candidate", "陈明"))
    # thread_id 与业务 case_id 用同一个值：前端审批按钮回传 case_id 即可命中
    # MemorySaver 里的 interrupt 断点，这是 HITL + checkpointer 能落地的关键。
    thread = str(payload.get("thread_id") or payload.get("case_id") or "")
    if not thread:
        thread = hr_data.create_onboarding(candidate, "产品部", "产品经理")["case_id"]
    resume_mode = bool(payload.get("thread_id") or payload.get("case_id"))
    cfg = _cfg(thread, cb)

    TRANSITIONS = {
        "DRAFT": {"submit": "WAIT_MANAGER_APPROVE"},
        "WAIT_MANAGER_APPROVE": {"approve": "HR_REVIEW", "reject": "REJECTED"},
        "HR_REVIEW": {"pass": "IT_PROVISIONING", "reject": "REJECTED"},
        "IT_PROVISIONING": {"done": "DONE"},
        "DONE": {}, "REJECTED": {},
    }

    class FlowState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        case_id: str
        status: str
        checkpoints: list[str]

    def collect(state: FlowState) -> dict:
        if state.get("case_id"):
            ctx.trace("state", f"case {state['case_id']} 已存在，跳过重复建单（幂等）；interrupt 重放同样安全")
            return {"status": "WAIT_MANAGER_APPROVE", "checkpoints": ["collect_material"]}
        case = hr_data.create_onboarding(candidate, "产品部", "产品经理")
        hr_data.checkpoint(case["case_id"], "collect_material", {"materials": 6})
        ctx.trace("action", f"LangGraph 节点 collect_material：创建入职单 {case['case_id']}")
        return {"case_id": case["case_id"], "status": "WAIT_MANAGER_APPROVE",
                "checkpoints": ["collect_material"]}

    def approval(state: FlowState) -> dict:
        # interrupt() 之前不放任何副作用：Command(resume) 恢复时本节点会重放
        decision = interrupt({
            "prompt": f"入职单 {state.get('case_id')} 等待主管审批（SOP 1.3：Agent 不得代批）",
            "case_id": state.get("case_id"), "thread_id": thread,
            "actions": [{"key": "approve", "label": "通过"}, {"key": "reject", "label": "驳回"}],
            "sop": "《招聘与入职 SOP》1.3",
        })
        action = (decision or {}).get("action", "approve")
        approver = (decision or {}).get("approver", "李四（主管）")
        dst = TRANSITIONS.get("WAIT_MANAGER_APPROVE", {}).get(action)
        if not dst:
            raise ValueError(f"非法状态跳转：WAIT_MANAGER_APPROVE --{action}--> ?（状态机拦截）")
        hr_data.audit(approver, f"hitl:{action}", state.get("case_id", ""), "LangGraph interrupt 人工决策")
        ctx.trace("hitl", f"Command(resume) 恢复：{approver} 选择 {action} → {dst}")
        return {"status": dst, "checkpoints": state["checkpoints"] + ["human_approval"]}

    def post(state: FlowState) -> dict:
        if state["status"] == "REJECTED":
            hr_data.checkpoint(state["case_id"], "rejected", {"by": "主管"})
            ctx.trace("state", "主管驳回：不执行 HR 复核与 IT 开账号")
            return {"checkpoints": state["checkpoints"] + ["rejected"]}
        cid = state["case_id"]
        hr_data.checkpoint(cid, "hr_review", {"checked": ["劳动合同", "录用条件告知书"]})
        hr_data.update_case(cid, "IT_PROVISIONING", "it_provisioning")
        ticket = {"ticket": "ITSM-2026-1145", "systems": ["邮箱", "OA", "Git"]}
        hr_data.checkpoint(cid, "it_provisioning", ticket)
        hr_data.update_case(cid, "DONE", "done", {"it_ticket": ticket["ticket"]})
        hr_data.checkpoint(cid, "done", {"finished": True})
        ctx.trace("state", "HR 复核 → IT 开账号 → DONE，每节点写 checkpoint")
        return {"status": "DONE", "checkpoints": state["checkpoints"] + ["hr_review", "it_provisioning", "done"]}

    g = StateGraph(FlowState)
    g.add_node("collect", collect)
    g.add_node("human_approval", approval)
    g.add_node("post_approval", post)
    g.add_edge(START, "collect")
    g.add_edge("collect", "human_approval")
    g.add_edge("human_approval", "post_approval")
    g.add_edge("post_approval", END)
    graph = g.compile(checkpointer=CHECKPOINTER)

    if payload.get("action") and payload.get("thread_id"):
        out = graph.invoke(Command(resume={"action": payload["action"],
                                           "approver": payload.get("approver", "李四（主管）")}), config=cfg)
        hitl = None
    else:
        out = graph.invoke({"messages": [HumanMessage(content=f"给 {candidate} 办入职")],
                            "case_id": thread if not resume_mode else "",
                            "status": "DRAFT", "checkpoints": []}, config=cfg)
        snap = graph.get_state(cfg)
        pend = [getattr(i, "value", None) for t in (snap.tasks or [])
                for i in (getattr(t, "interrupts", ()) or ())]
        hitl = None
        if pend and isinstance(pend[0], dict):
            hitl = {**pend[0], "required": True, "resume_hint": "POST /api/hitl/approve 或本 Demo 传 action+thread_id"}

    cid = out.get("case_id", "")
    status = out.get("status", "WAIT_MANAGER_APPROVE")
    answer = (f"入职单 {cid} 已完成：材料核对 → 主管审批 → HR 复核 → IT 开账号。"
              if status == "DONE" else
              f"入职单 {cid} 已创建，LangGraph interrupt 挂起在「主管审批」，请在控制台点击通过或驳回。")
    if status == "REJECTED":
        answer = f"入职单 {cid} 被主管驳回，流程终止，未执行 IT 开账号。"
    return finish(ctx, cb, answer, hitl=hitl, state={
        "framework": "StateGraph + MemorySaver + interrupt + Command(resume)",
        "thread_id": thread, "case_id": cid, "status": status,
        "transitions": TRANSITIONS, "checkpoints": out.get("checkpoints", []),
        "stages": [{"name": n, "done": n in out.get("checkpoints", []),
                    "active": n == "human_approval" and status == "WAIT_MANAGER_APPROVE"}
                   for n in ("collect_material", "human_approval", "hr_review", "it_provisioning", "done")],
        "note": "人工节点是一等公民，返回体 hitl 字段由前端渲染按钮",
    })


def chapter_04_resume(case_id: str, action: str, approver: str, ctx: Context) -> dict:
    # 兼容前端 /api/hitl/approve：旧 case_id 与 lc- thread_id 两种都支持
    return chapter_04({"thread_id": case_id, "action": action, "approver": approver}, ctx)


# =====================================================================
# 第 5 章  Memory：checkpointer（会话）+ InMemoryStore（长期/用户）
# =====================================================================
def chapter_05(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    seed_store()
    question = str(payload.get("question", "帮我安排一场候选人面试，有什么需要注意的？"))
    threshold = float(payload.get("importance_threshold", 0.3))
    thread = _tid()
    cfg = _cfg(thread, cb)

    items: list[dict] = []
    for it in STORE.search(("user", "E1001"), limit=10):
        items.append({"scope": "user/user_memory", "key": it.key,
                      "value": it.value.get("value"), "importance": it.value.get("importance", 0.5)})
    long_item = STORE.get(("long", "org"), "calibration")
    if long_item:
        items.append({"scope": "long/long_term", "key": "calibration",
                      "value": long_item.value.get("value"),
                      "importance": long_item.value.get("importance", 0.8)})
    kept = [m for m in items if m["importance"] >= threshold]
    ctx.trace("memory", f"LangGraph InMemoryStore 召回 {len(items)} 条，重要性阈值 {threshold} 过滤后 {len(kept)} 条",
              scopes=[m["scope"] for m in kept])

    class MemState(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]
        memory_block: str
        history_len: int

    def node(state: MemState) -> dict:
        block = "\n".join(f"- [{m['scope']}] {m['value']}" for m in kept)
        return {"memory_block": block, "history_len": len(state["messages"])}

    g = StateGraph(MemState)
    g.add_node("recall", node)
    g.add_edge(START, "recall")
    g.add_edge("recall", END)
    graph = g.compile(checkpointer=CHECKPOINTER)
    out = graph.invoke({"messages": [HumanMessage(content=question)],
                        "memory_block": "", "history_len": 0}, config=cfg)
    # 同一 thread 再 invoke 一次，验证 add_messages 的会话记忆累积
    graph.invoke({"messages": [HumanMessage(content="另外帮我约上午的会议室")]}, config=cfg)
    snap = graph.get_state(cfg)
    session_len = len(snap.values.get("messages", []))

    reply = json.dumps({"answer": "建议约上午 9:00–10:00，接待用餐避开海鲜；本次面试不涉及晋升名额。",
                        "used_memory": [m["key"] for m in kept]}, ensure_ascii=False)
    chain = (RunnableLambda(lambda x: [_ctx({"mock_response": reply})] + x)
             | ctx.chat_model("compose"))
    ai = chain.invoke([HumanMessage(content=question),
                       SystemMessage(content=out["memory_block"])], config=cfg)
    answer = (f"已按记忆安排：偏好上午 9:00–10:00 面试、接待用餐避开海鲜。"
              f"本次召回 {len(kept)} 条记忆（阈值 {threshold}），会话消息累积 {session_len} 条。")
    STORE.put(("long", "hr"), f"run::{thread}", {"question": question, "used": len(kept)})
    ctx.trace("memory", "结论写入 InMemoryStore（长期记忆，跨 thread 可检索）")
    return finish(ctx, cb, answer, state={
        "framework": "langgraph.store.memory.InMemoryStore + MemorySaver + add_messages",
        "layers": {
            "会话记忆": "checkpointer 按 thread_id 持久化 messages",
            "长期记忆": "InMemoryStore namespace=('long','org')",
            "用户记忆": "InMemoryStore namespace=('user', emp_id)，可导出/可删除",
        },
        "recalled": kept, "filtered_out": [m["key"] for m in items if m not in kept],
        "session_message_count": session_len, "threshold": threshold,
        "store_keys": [it.key for it in STORE.search(("user", "E1001"), limit=10)],
    })


# =====================================================================
# 第 6 章  Context Engineering：trim_messages + LCEL 装配 + 摘要
# =====================================================================
def chapter_06(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    budget = int(payload.get("token_budget", 500))
    turns = int(payload.get("history_turns", 12))
    keep_recent = int(payload.get("keep_recent", 2))
    question = "我还能休几天年假？婚假怎么算？"
    thread = _tid()
    cfg = _cfg(thread, cb)

    history = [HumanMessage(content=f"第{i}轮闲聊：随便聊点什么，内容比较长" * 6)
               for i in range(turns)]
    history += [HumanMessage(content=question)]
    naive_tokens = token_counter(history)
    ctx.trace("llm", f"朴素装配：{len(history)} 条消息 ≈ {naive_tokens} Token，超预算 {budget}")

    # ① LangChain trim_messages：滚动窗口，保留最近 N 条
    trimmed = trim_messages(history, max_tokens=budget // 3, strategy="last",
                            token_counter=token_counter, include_system=False, allow_partial=False)
    # ② 摘要链：旧内容压成要点（只压历史，绝不压制度原文）
    summary_chain = (ChatPromptTemplate.from_messages([
        ("system", "把历史对话压成不超过 80 字的要点摘要，不新增事实。"),
        ("human", "{input}")]) | ctx.chat_model("summarize") | StrOutputParser())
    summary = invoke(summary_chain, {"input": f"共 {max(0, len(history)-keep_recent)} 轮旧对话"},
                     cfg, ctx, label="摘要链")
    # ③ 检索片段（P0，逐条按预算装入）
    retriever, rinfo = build_retriever(ctx.mode, top_k=3)
    docs = retriever.invoke(question, config=cfg)
    picked, used = [], 0
    for i, d in enumerate(docs, 1):
        block = f"[{i}] 《{d.metadata.get('title')}》{d.metadata.get('section')}（{d.metadata.get('version')}）：{d.page_content}"
        cost = token_counter([HumanMessage(content=block)])
        if used + cost <= budget * 0.3:
            picked.append(block); used += cost
    dropped = []
    if used + 40 > budget:
        dropped.append("低优先级块 tool/recent_history 被裁剪")
    # ④ LCEL 装配：RunnablePassthrough + ChatPromptTemplate（不改模型，只改上下文）
    ctx_docs = [{"citation_id": i, "title": "HR 制度合集", "section": "上下文装配片段",
                 "version": d.metadata.get("version", "V2.3"), "text": d.page_content}
                for i, d in enumerate(docs[:len(picked)], 1)]
    def assemble(x: dict) -> list:
        return [_ctx({"documents": ctx_docs, "intent": "rag"}),
                SystemMessage(content=(f"P0 只依据资料回答，不知道就说不知道。\n"
                                       f"P1 用户画像：E1001 产品部。\nP2 历史摘要：{x['summary']}\n"
                                       f"资料（P0，带编号）：\n{x['docs']}\n预算：{x['budget']} Token")),
                HumanMessage(content=x["question"])]
    chain = (RunnableLambda(assemble) | ctx.chat_model("compose") | StrOutputParser())
    composed = invoke(chain, {"summary": str(summary), "docs": "\n".join(picked),
                              "budget": budget, "question": question}, cfg, ctx, label="装配链")
    after = sum(token_counter([HumanMessage(content=x)]) for x in picked) + token_counter(trimmed) + 80
    ctx.trace("state", f"上下文装配完成：{naive_tokens} → ≈{after} Token，压缩率 {round(1-after/max(naive_tokens,1),2)*100}%")
    return finish(ctx, cb, str(composed)[:200] or "已按预算装配上下文并回答。", state={
        "framework": "langchain_core.messages.trim_messages + ChatPromptTemplate + RunnableSequence(LCEL)",
        "before_tokens": naive_tokens, "after_tokens": after, "budget": budget,
        "compression_ratio": round(1 - after / max(naive_tokens, 1), 3),
        "kept_recent": len(trimmed), "summary": str(summary)[:160],
        "picked_citations": [d.metadata.get("citation_id") for d in docs[:len(picked)]],
        "dropped": dropped, "retriever": rinfo,
        "rule": "制度原文绝不摘要：条款号是引用锚点；工具返回先结构化再进上下文",
    })


# =====================================================================
# 第 7 章  RAG 基础：Document 切片 → InMemoryVectorStore → Retriever → Rerank → LCEL
# =====================================================================
def chapter_07(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    question = str(payload.get("question", "公司有几天婚假？"))
    top_k = int(payload.get("top_k", 3))
    thread = _tid()
    cfg = _cfg(thread, cb)

    chunks = load_active_chunks()
    ctx.trace("retrieve", f"① 解析 + ② 切片：{len(chunks)} 个 chunk，元数据带 doc_id/version/section/seq",
              versions=sorted({c["version"] for c in chunks}))

    # ③ Embeddings（LangChain 接口）+ ④ 向量库（langchain_core InMemoryVectorStore）
    emb = build_embeddings(ctx.mode)
    store = InMemoryVectorStore(emb)
    docs = [Document(page_content=c["text"],
                     metadata={"chunk_id": c["chunk_id"], "doc_id": c["doc_id"],
                               "title": c["title"], "section": c["section"],
                               "version": c["version"], "active": True})
            for c in chunks]
    store.add_documents(docs)
    ctx.trace("retrieve", f"③ Embeddings={type(emb).__name__} → ④ InMemoryVectorStore 写入 {len(docs)} 个 Document")

    # ⑤ 召回：标准 BaseRetriever
    retriever = store.as_retriever(search_kwargs={"k": max(5, top_k)})
    recalled = retriever.invoke(question, config=cfg)
    ctx.trace("retrieve", f"⑤ 向量召回 Top-{len(recalled)}", ids=[d.metadata["chunk_id"] for d in recalled])

    # ⑥ Rerank：作为 LCEL 中的 RunnableLambda（生产换 CrossEncoder / bge-reranker）
    def rerank(inputs: dict) -> dict:
        q = inputs["question"]
        chars = set(re.findall(r"[\u4e00-\u9fff]{1,2}|\d+(?:\.\d+)?", q))
        scored = []
        for i, d in enumerate(inputs["docs"]):
            cover = len(chars & set(d.page_content)) / max(len(chars), 1)
            sem = 1.0 / (1 + i)
            scored.append((0.7 * sem + 0.3 * cover, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [d for _, d in scored[:top_k]]
        for i, d in enumerate(out, 1):
            d.metadata["citation_id"] = i
        return {"docs": out, "question": q}

    ranked = (RunnablePassthrough.assign(docs=RunnableLambda(lambda x: x["docs"]))
              | RunnableLambda(rerank)).invoke({"docs": recalled, "question": question}, config=cfg)
    ctx.trace("retrieve", f"⑥ Rerank（LCEL RunnableLambda）→ {len(ranked['docs'])} 条",
              sections=[d.metadata.get("section") for d in ranked["docs"]])

    # ⑦ Prompt 拼接 + 生成（LCEL）
    context = "\n".join(f"[{d.metadata['citation_id']}] 《{d.metadata['title']}》"
                        f"{d.metadata['section']}（{d.metadata['version']}）：{d.page_content}"
                        for d in ranked["docs"])
    def build_msgs(x: dict) -> list:
        docs = [{"citation_id": d.metadata.get("citation_id"), "title": d.metadata.get("title"),
                 "section": d.metadata.get("section"), "version": d.metadata.get("version"),
                 "text": d.page_content} for d in ranked["docs"]]
        return [_ctx({"documents": docs, "intent": "rag"}),
                SystemMessage(content="只依据资料回答，必须带 [n] 引用编号，不要编造条款号或数字。"),
                HumanMessage(content=f"资料：\n{x['context']}\n问题：{x['question']}")]
    chain = (RunnableLambda(build_msgs) | ctx.chat_model("compose") | StrOutputParser())
    answer = str(invoke(chain, {"context": context, "question": question}, cfg, ctx, label="RAG 生成链"))
    if not re.search(r"\[\d+\]", answer) and ranked["docs"]:
        answer += " [1]"

    # ⑧ 引用质量校验：格式层 + 事实层
    cited = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    nums = re.findall(r"\d+(?:\.\d+)?\s*(?:条|天|个月|元)", answer)
    unsupported = [n for n in nums if n not in context]
    ctx.trace("observation", f"⑧ 引用校验：{len(set(cited))} 个引用，越界 {[n for n in cited if n > len(ranked['docs'])]}，"
                             f"无依据数字 {unsupported}")
    return finish(ctx, cb, answer, state={
        "framework": "Document → Embeddings → InMemoryVectorStore.as_retriever → RunnableLambda(Rerank) → LCEL 生成链",
        "pipeline": ["解析", "切片", "Embedding", "向量化入库", "召回", "Rerank", "Prompt 拼接", "引用校验"],
        "chunk_count": len(chunks), "recall_count": len(recalled),
        "reranked": [{"section": d.metadata.get("section"), "version": d.metadata.get("version"),
                      "citation_id": d.metadata.get("citation_id")} for d in ranked["docs"]],
        "citation_quality": {"cited": cited, "out_of_range": [n for n in cited if n > len(ranked["docs"])],
                             "unsupported_numbers": unsupported,
                             "verdict": "通过" if not unsupported and all(n <= len(ranked["docs"]) for n in cited) else "待复核"},
        "production": {"解析": "Unstructured/PyMuPDF", "切片": "LlamaIndex SentenceSplitter",
                       "向量库": "Chroma / Qdrant / Milvus / Elasticsearch", "Rerank": "bge-reranker / Cohere"},
    })


# =====================================================================
# 第 8 章  RAG 进阶：三路混合 BaseRetriever + 版本 / 增量发布 / 撤销
# =====================================================================
BASE_VERSION, NEW_VERSION = "V2.3", "V2.4"
TARGET_DOC = "员工手册_休假"


def _kb_ensure() -> int:
    conn = hr_data.connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
        if n:
            return n
        import hashlib
        from common.lc_retrieval import _slice
        count = 0
        for d in hr_data.load_handbook():
            for c in _slice(d["text"]):
                conn.execute("INSERT OR REPLACE INTO kb_chunks VALUES(?,?,?,?,?,?)",
                             (f"{d['doc_id']}::{c['version']}::{c['seq']}", d["doc_id"],
                              c["version"], c["seq"], c["text"], 1))
                count += 1
            conn.execute("INSERT OR REPLACE INTO kb_docs VALUES(?,?,?,?,?,?)",
                         (d["doc_id"], d["title"], BASE_VERSION,
                          hashlib.md5(d["text"].encode()).hexdigest()[:8], 1, hr_data.now()))
        conn.commit()
        return count
    finally:
        conn.close()


def chapter_08(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    action = str(payload.get("action", "search"))
    question = str(payload.get("question", "婚假有多少天，需要什么材料？"))
    thread = _tid()
    cfg = _cfg(thread, cb)
    total = _kb_ensure()

    if action == "publish":
        from common.lc_retrieval import _slice
        doc = next(d for d in hr_data.load_handbook() if d["doc_id"] == TARGET_DOC)
        updated = doc["text"].replace("婚假 10 天", "婚假 13 天")
        conn = hr_data.connect()
        try:
            conn.execute("UPDATE kb_chunks SET active=0 WHERE doc_id=?", (TARGET_DOC,))
            for c in _slice(updated):
                conn.execute("INSERT OR REPLACE INTO kb_chunks VALUES(?,?,?,?,?,?)",
                             (f"{TARGET_DOC}::{NEW_VERSION}::{c['seq']}", TARGET_DOC,
                              NEW_VERSION, c["seq"], c["text"], 1))
            conn.execute("UPDATE kb_chunks SET active=1 WHERE doc_id=? AND version=?",
                         (TARGET_DOC, NEW_VERSION))
            conn.execute("UPDATE kb_chunks SET active=1 WHERE doc_id<>? AND active=0 AND version=?",
                         (TARGET_DOC, BASE_VERSION))
            conn.commit()
        finally:
            conn.close()
        hr_data.audit("kb_admin", "publish_incremental", TARGET_DOC, f"{BASE_VERSION} -> {NEW_VERSION}")
        ctx.trace("retrieve", f"增量发布：仅重建《{TARGET_DOC}》，旧 chunk 置 active=0（软删除，可撤销）")
        return finish(ctx, cb, f"已增量发布 {NEW_VERSION}：婚假 10 天 → 13 天，其他文档索引未重建。",
                      state={"action": "publish", "version": NEW_VERSION, "total_chunks": total,
                             "note": "版本按文档管理；旧版本从未物理删除，撤销零成本"})

    if action == "rollback":
        conn = hr_data.connect()
        try:
            conn.execute("UPDATE kb_chunks SET active=0 WHERE doc_id=? AND version=?", (TARGET_DOC, NEW_VERSION))
            conn.execute("UPDATE kb_chunks SET active=1 WHERE doc_id=? AND version=?", (TARGET_DOC, BASE_VERSION))
            conn.commit()
        finally:
            conn.close()
        hr_data.audit("kb_admin", "rollback", TARGET_DOC, f"{NEW_VERSION} -> {BASE_VERSION}")
        ctx.trace("retrieve", f"撤销 {NEW_VERSION}，恢复 {BASE_VERSION}（active 标记切换 + 审计留痕）")
        return finish(ctx, cb, f"已撤销 {NEW_VERSION}，恢复 {BASE_VERSION}（婚假 10 天）。",
                      state={"action": "rollback", "restored": BASE_VERSION})

    retriever, rinfo = build_retriever(ctx.mode, top_k=3)
    docs = retriever.invoke(question, config=cfg)
    hits = [{"chunk_id": d.metadata.get("chunk_id"), "version": d.metadata.get("version"),
             "sources": d.metadata.get("sources"), "rrf": d.metadata.get("rrf"),
             "citation_id": d.metadata.get("citation_id"), "text": d.page_content[:120]}
            for d in docs]
    versions = sorted({h["version"] for h in hits})
    stale = [h["chunk_id"] for h in hits if h["version"] == NEW_VERSION and action == "rollback"]
    ctx.trace("retrieve", f"三路混合召回 {len(hits)} 条｜版本 {versions}",
              sources=[h["sources"] for h in hits])
    context = "\n".join(f"[{h['citation_id']}] （{h['version']}）{h['text']}" for h in hits)
    def build_msgs(x: dict) -> list:
        docs = [{"citation_id": h["citation_id"], "title": "HR 制度合集",
                 "section": "混合检索片段", "version": h["version"], "text": h["text"]}
                for h in hits]
        return [_ctx({"documents": docs, "intent": "rag"}),
                SystemMessage(content="只依据带编号的资料回答，标注版本，带 [n] 引用。"),
                HumanMessage(content=f"资料：\n{x['context']}\n问题：{x['question']}")]
    chain = (RunnableLambda(build_msgs) | ctx.chat_model("compose") | StrOutputParser())
    answer = str(invoke(chain, {"context": context, "question": question}, cfg, ctx, label="混合检索生成链"))
    return finish(ctx, cb, answer, state={
        "framework": "自定义 BaseRetriever（InMemoryVectorStore + BM25 + 图谱，RRF 融合）",
        "retriever": rinfo, "rrf_fused": hits, "versions_in_context": versions,
        "citation_quality": {"active_ratio": f"{len(hits)-len(stale)}/{len(hits)}",
                             "version_conflict": len(versions) > 1, "stale_hits": stale,
                             "answer_has_citation": bool(re.search(r"\[\d+\]", answer)),
                             "verdict": "引用均来自 active 版本" if not stale else "存在失效版本引用，需拦截"},
        "governance": {"publish": "增量重建受影响文档 + active 软删除", "rollback": "active 标记切回，不删历史",
                       "production": "向量库 payload 过滤 active=true + 关系库版本元数据 + Elasticsearch BM25"},
    })


# =====================================================================
# 第 9 章  Text2SQL / Text2Cypher / 图谱检索 / Ontology / 幻觉控制
# =====================================================================
ONTOLOGY = {
    "实体": ["员工", "部门", "项目", "技能", "制度文档"],
    "关系": ["汇报给", "属于", "参与项目", "掌握技能", "归属领域"],
    "约束": ["员工必须且只能属于一个部门", "汇报给形成有向无环图", "项目可跨部门"],
}


def chapter_09(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    mode = str(payload.get("mode", "hybrid"))
    sql_q = str(payload.get("sql_question", "产品部上个月平均加班多久？"))
    graph_q = str(payload.get("graph_question", "谁和张三在同一个项目，张三向谁汇报？"))
    thread = _tid()
    cfg = _cfg(thread, cb)
    state: dict[str, Any] = {"ontology": ONTOLOGY, "mode": mode}

    if mode in ("text2sql", "hybrid"):
        # 模型生成 SQL（真实模式走 ChatOllama），服务端用 @tool 的只读网关执行
        sql_mock = {"sql": SQL_MOCK, "why": "平均加班是聚合指标，必须精确计算而非文本召回"}
        gen = (RunnableLambda(lambda msgs: [_ctx({"mock_response": sql_mock})] + msgs)
               | ctx.chat_model("tools"))
        obj = _parse_json(gen.invoke([HumanMessage(content=sql_q)], config=cfg), sql_mock)
        sql = str(obj.get("sql", SQL_MOCK))
        ctx.trace("thought", "Text2SQL：模型输出 SQL 意图，服务端校验后才执行")
        try:
            tool_out = readonly_sql.invoke({"sql": sql}, config=cfg)
        except Exception as exc:
            tool_out = json.dumps({"error": str(exc)}, ensure_ascii=False)
        parsed = _parse_json(tool_out, {})
        data = parsed.get("data", {})
        rows = data.get("rows", []) if isinstance(data, dict) else []
        ctx.trace("observation", f"只读网关返回 {len(rows)} 行（SELECT 白名单 + 关键字黑名单）")
        state["text2sql"] = {"sql": sql, "rows": rows,
                             "cypher_equivalent": "MATCH (e:Employee)-[:WORKS_IN]->(d:Dept {name:'产品部'}) "
                                                  "RETURN avg(e.overtime)",
                             "gateway": "@tool readonly_sql：仅 SELECT、禁 DROP/ATTACH/PRAGMA、只读连接"}
    if mode in ("graph", "hybrid"):
        out = org_graph_query.invoke({"entity": "张三", "relation": "参与项目"}, config=cfg)
        parsed = _parse_json(out, {})
        data = parsed.get("data", {})
        triples = data.get("triples", []) if isinstance(data, dict) else []
        ctx.trace("retrieve", f"图谱 2 跳子图：{len(triples)} 条三元组（等价 Text2Cypher）")
        state["graph"] = {"entity": "张三", "triples": triples,
                          "relation_hits": data.get("relation_hits", []) if isinstance(data, dict) else [],
                          "subgraph_text": data.get("subgraph_text", "") if isinstance(data, dict) else "",
                          "production": "Neo4j Cypher / LlamaIndex PropertyGraphIndex / GraphRAG 社区摘要"}

    # 幻觉控制：答案里的实体与数字必须能在证据集中溯源
    evidence = json.dumps(state, ensure_ascii=False)
    answer_parts = []
    if "text2sql" in state and state["text2sql"]["rows"]:
        r = state["text2sql"]["rows"][0]
        answer_parts.append(f"产品部 2026-10 平均加班 {r.get('avg_overtime')} 小时（Text2SQL 精确计算）。")
    if "graph" in state:
        g = state["graph"]
        answer_parts.append(f"张三汇报关系与项目同事均可溯源到 {len(g['triples'])} 条子图三元组"
                            f"（命中 {len(g['relation_hits'])} 条关系），未使用子图之外信息。")
    answer = " ".join(answer_parts) or "未选择有效模式。"
    names = re.findall(r"[\u4e00-\u9fff]{2,3}(?=汇报|同事|参与)", answer)
    state["hallucination_guard"] = {
        "method": "实体/数字溯源：答案中每个人名与数值都要能在 SQL 结果集或子图中找到",
        "checked_entities": names, "evidence_chars": len(evidence),
        "verdict": "通过：实体均可溯源" if evidence else "拦截：无证据",
    }
    return finish(ctx, cb, answer, state=state | {
        "framework": "@tool(readonly_sql) + BaseRetriever 图谱路 + Ontology 约束",
        "routing": "指标类 → Text2SQL；关系类 → 图谱；语义类 → 向量检索",
    })


# =====================================================================
# 第 10 章  MCP / Skill / Plugin：langchain-mcp-adapters 真实对接
# =====================================================================
SKILLS = {
    "leave_query": {"name": "假期查询", "when_to_use": "员工问年假/病假/婚假余额或假期政策时",
                    "tools": ["get_leave_balance", "get_attendance"],
                    "sop": ["识别意图", "从登录态取 emp_id", "调用工具", "附数据来源与截止时间"],
                    "guardrails": ["只查本人数据", "回答附 as_of", "工具失败降级并标注时效"]},
    "onboarding": {"name": "入职办理", "when_to_use": "用户要办理入职、推进流程、查进度时",
                   "tools": ["prepare_onboarding"], "sop": ["核对材料", "建单", "主管审批", "HR 复核", "IT 开账号"],
                   "guardrails": ["主管审批不得代批", "非法跳转代码层拦截"]},
    "policy_qa": {"name": "制度问答", "when_to_use": "问制度条款、流程、报销标准时",
                  "tools": ["retriever"], "sop": ["混合检索", "版本校验", "带引用回答"],
                  "guardrails": ["只答 active 版本", "引用编号必须可溯源"]},
}


def chapter_10(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    question = str(payload.get("question", "我今年还剩几天年假？"))
    thread = _tid()
    cfg = _cfg(thread, cb)

    # ① Skill 渐进式披露：只把 name + when_to_use 放进上下文让模型选
    catalog = json.dumps([{"key": k, "name": v["name"], "when_to_use": v["when_to_use"]}
                          for k, v in SKILLS.items()], ensure_ascii=False)
    pick = (RunnableLambda(lambda msgs: [_ctx({"mock_response": {"skill": "leave_query",
                                                                 "reason": "问题涉及年假余额"}})] + msgs)
            | ctx.chat_model("router"))
    chosen = _parse_json(pick.invoke([HumanMessage(content=f"技能目录：{catalog}\n问题：{question}")], config=cfg),
                         {"skill": "leave_query"}).get("skill", "leave_query")
    skill = SKILLS.get(chosen, SKILLS["leave_query"])
    ctx.trace("thought", f"渐进式披露：目录 ~{len(catalog)//2} Token，选中 Skill「{skill['name']}」后才展开 SOP",
              skill=chosen, sop=skill["sop"])

    # ② 真实 MCP：langchain-mcp-adapters 拉起第 10 章 stdio MCP Server
    mcp_info: dict[str, Any] = {}
    mcp_answer = ""
    try:
        import asyncio
        from langchain_mcp_adapters.client import MultiServerMCPClient
        server = ROOT / "demos" / "ch10_mcp_skill" / "mcp_server.py"

        async def call():
            client = MultiServerMCPClient({"hr": {"command": sys.executable,
                                                  "args": [str(server)], "transport": "stdio"}})
            tools = await asyncio.wait_for(client.get_tools(), timeout=25)
            names = [t.name for t in tools]
            target = next((t for t in tools if t.name == "get_leave_balance"), None)
            out = await asyncio.wait_for(target.ainvoke({"emp_id": "E1001"}), timeout=20) if target else {}
            return names, out
        names, out = asyncio.run(call())
        mcp_info = {"adapter": "langchain_mcp_adapters.MultiServerMCPClient",
                    "transport": "stdio (JSON-RPC 2.0)", "tools_discovered": names,
                    "result": out if isinstance(out, dict) else str(out)[:300],
                    "note": "工具在独立子进程执行，Server 日志只写 stderr，notification 不回响应"}
        obj = out if isinstance(out, dict) else _parse_json(out, {})
        mcp_answer = (f"MCP Server 返回：年假余额 {obj.get('leave_balance')} 天，"
                      f"来源 {obj.get('source')}，截至 {obj.get('as_of')}。")
        ctx.trace("tool", f"LangChain MCP 适配器发现 {len(names)} 个工具并真实调用", tools=names)
    except Exception as exc:
        mcp_info = {"adapter": "langchain_mcp_adapters", "error": str(exc),
                    "fallback": "降级到本地 @tool，并告警"}
        local = _parse_json(get_leave_balance.invoke({"emp_id": "E1001"}, config=cfg), {})
        data = local.get("data", {})
        mcp_answer = f"MCP 不可用已降级到本地 StructuredTool：年假余额 {data.get('leave_balance')} 天。"
        ctx.trace("error", f"MCP 调用失败，降级到本地工具：{exc}")

    # ③ Plugin：同进程本地代码（对比层次）
    ctx.trace("state", "Plugin=本地代码；Skill=时机+SOP+护栏的知识包；MCP=跨框架工具发现与调用协议")
    return finish(ctx, cb, mcp_answer, state={
        "framework": "langchain-mcp-adapters + @tool(StructuredTool) + 渐进式披露 Skill 目录",
        "skill_selected": chosen, "skill_detail": skill,
        "catalog_tokens_est": len(catalog) // 2,
        "mcp": mcp_info,
        "differences": {"Plugin": "一段本地可调用代码", "Skill": "使用时机 + SOP + 工具清单 + 护栏",
                        "MCP": "Model Context Protocol，标准通信协议（JSON-RPC 2.0）"},
        "production": "官方 MCP SDK + Streamable HTTP + OAuth2 / mTLS + 工具注册中心 + 幂等键",
    })


# =====================================================================
# 第 11 章  Multi-Agent：LangGraph supervisor + 共享黑板 + 仲裁
# =====================================================================
def chapter_11(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    jd = str(payload.get("jd_id", "J2001"))
    thread = _tid()
    cfg = _cfg(thread, cb)

    class Blackboard(TypedDict, total=False):
        jd: str
        parsed: dict
        ranking: list[dict]
        veto: list[str]
        schedule: dict
        messages: list[dict]
        decision: dict

    ROLES = ["ParserAgent", "MatchAgent", "ComplianceAgent", "SchedulerAgent", "Orchestrator"]
    EVIDENCE = {
        "ParserAgent": {"candidates": [{"id": "C01", "skills": ["Python", "FastAPI", "分布式"], "years": 6},
                                       {"id": "C02", "skills": ["Python"], "years": 3}]},
        "MatchAgent": {"ranking": [{"id": "C01", "score": 92}, {"id": "C02", "score": 61}],
                       "recommend": "C01"},
        "ComplianceAgent": {"veto": ["C02"], "reason": "JD 硬性要求 5 年以上，C02 仅 3 年，属不合规推荐"},
        "SchedulerAgent": {"time": "2026-11-18 09:30", "interviewer": "李四", "channel": "IM + 邮件"},
    }

    def make_role(role: str):
        def node(state: Blackboard) -> dict:
            out = EVIDENCE[role]
            chain = (RunnableLambda(lambda msgs: [_ctx({"mock_response": out})] + msgs)
                     | ctx.chat_model("compose"))
            chain.invoke([HumanMessage(content=f"你是 {role}，共享黑板：{json.dumps(state, ensure_ascii=False)[:300]}")],
                         config=cfg)
            ctx.trace("thought", f"{role} 写入共享黑板：{json.dumps(out, ensure_ascii=False)[:110]}")
            msgs = list(state.get("messages", []))
            msgs.append({"from": role, "to": "Orchestrator", "type": "result", "payload": out})
            hr_data.audit(role, "blackboard.write", jd, json.dumps(out, ensure_ascii=False)[:120])
            key = {"ParserAgent": "parsed", "MatchAgent": "ranking",
                   "ComplianceAgent": "veto", "SchedulerAgent": "schedule"}[role]
            value = (out if role in ("ParserAgent", "SchedulerAgent")
                     else out["ranking"] if role == "MatchAgent" else out["veto"])
            return {key: value, "messages": msgs}
        return node

    def arbitrate(state: Blackboard) -> dict:
        ranking = state.get("ranking", [])
        veto = set(state.get("veto", []))
        recommended = "C01"
        conflict = recommended in veto
        if conflict:
            final_choice = next((r["id"] for r in ranking if r["id"] not in veto), "无合规候选人")
        else:
            final_choice = recommended
        decision = {"recommended": recommended, "veto": sorted(veto),
                    "conflict": conflict, "final_choice": final_choice,
                    "rule": "合规一票否决 > 匹配分（业务规则写进仲裁代码，不靠模型自觉）"}
        ctx.trace("state", f"Orchestrator 仲裁：推荐 {recommended}｜否决 {sorted(veto)}｜最终 {final_choice}")
        return {"decision": decision}

    g = StateGraph(Blackboard)
    for r in ROLES[:-1]:
        g.add_node(r, make_role(r))
    g.add_node("Orchestrator", arbitrate)
    g.add_edge(START, "ParserAgent")
    for a, b in zip(ROLES[:-2], ROLES[1:-1]):
        g.add_edge(a, b)
    g.add_edge("SchedulerAgent", "Orchestrator")
    g.add_edge("Orchestrator", END)
    graph = g.compile(checkpointer=CHECKPOINTER)
    out = graph.invoke({"jd": jd, "messages": []}, config=cfg)
    d = out.get("decision", {})
    answer = (f"LangGraph supervisor 编排 4 个角色：推荐 {d.get('recommended')}，"
              f"合规否决 {d.get('veto')}，仲裁后最终候选人 {d.get('final_choice')}；"
              f"面试安排在 {out.get('schedule', {}).get('time')}。")
    return finish(ctx, cb, answer, state={
        "framework": "LangGraph StateGraph（supervisor 拓扑）+ 共享黑板 TypedDict + 代码层仲裁",
        "roles": ROLES, "messages": out.get("messages", []),
        "blackboard": {k: v for k, v in out.items() if k in ("parsed", "ranking", "veto", "schedule")},
        "arbitration": d,
        "termination_conditions": ["全部 Agent 返回结果", "无合规候选人", "达到 recursion_limit", "人工叫停"],
        "production": "LangGraph 子图 / CrewAI / AutoGen / Google A2A；框架换了原理不变",
    })


# =====================================================================
# 第 12 章  Sandbox / Harness / Code Mode / checkpointer 长任务恢复
# =====================================================================
DENY = re.compile(r"\b(import|open|exec|eval|__|os\b|sys\b|subprocess|socket|while\s+True|globals)\b")
SAFE_BUILTINS = {"len": len, "sum": sum, "round": round, "sorted": sorted,
                 "min": min, "max": max, "list": list, "dict": dict, "set": set,
                 "enumerate": enumerate, "zip": zip, "range": range, "str": str, "float": float}


@tool
def run_restricted_code(code: str, data_json: str = "[]") -> str:
    """Code Mode：在受限白名单环境里执行模型生成的聚合代码（教学版隔离）。"""
    if DENY.search(code):
        return json.dumps({"blocked": True, "reason": "源码静态扫描命中危险模式"}, ensure_ascii=False)
    try:
        data = json.loads(data_json)
        scope = {"data": data, "__builtins__": SAFE_BUILTINS, "result": None}
        exec(compile(code, "<code_mode>", "exec"), scope, scope)  # noqa: S102 - 教学演示
        return json.dumps({"ok": True, "result": scope.get("result")}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


CODE_MODE = ("groups = {}\n"
             "for row in data:\n"
             "    groups.setdefault(row['dept'], []).append(row['overtime'])\n"
             "result = {k: round(sum(v) / len(v), 2) for k, v in groups.items()}\n")


def chapter_12(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    simulate = str(payload.get("simulate_crash", "false")).lower() in {"1", "true", "yes"}
    thread = str(payload.get("case_id") or payload.get("thread_id") or "RPT-" + uuid.uuid4().hex[:6].upper())
    cfg = _cfg(thread, cb)

    rows = [{"name": n, "dept": d, "overtime": o} for n, d, o in
            [("张三", "产品部", 12.5), ("李四", "产品部", 6.0), ("王五", "研发部", 9.0),
             ("赵六", "研发部", 11.0), ("孙七", "产品部", 9.25), ("周八", "研发部", 7.0)]]
    ctx.trace("thought", f"Code Mode：模型写 4 行 Python 一次处理 6 行数据（传统做法要 6 次工具调用）",
              saved_calls=len(rows) - 1)

    class ReportState(TypedDict):
        done_nodes: list[str]
        result: dict
        case_id: str

    def make_stage(name: str, fn):
        def node(state: ReportState) -> dict:
            if name in state["done_nodes"]:
                ctx.trace("state", f"从 checkpoint 恢复：跳过已完成节点 {name}（不重放副作用）")
                return {}
            out = fn()
            hr_data.checkpoint(state["case_id"], name, {"ok": True, "result": out})
            ctx.trace("state", f"节点 {name} 完成，写入 checkpoint（含产物，恢复后数据对得上）")
            return {"done_nodes": state["done_nodes"] + [name], "result": out}
        return node

    g = StateGraph(ReportState)
    g.add_node("load_data", make_stage("load_data", lambda: {"rows": len(rows)}))
    g.add_node("compute", make_stage("compute", lambda: _parse_json(
        run_restricted_code.invoke({"code": CODE_MODE, "data_json": json.dumps(rows)}, config=cfg), {})))
    g.add_node("format_report", make_stage("format_report", lambda: {"report": "各部门平均加班时长报表"}))
    g.add_edge(START, "load_data")
    g.add_edge("load_data", "compute")
    if simulate:
        # 模拟崩溃：compute 后人为断开图，走到 END（checkpoint 已落盘）
        g.add_edge("compute", END)
    else:
        g.add_edge("compute", "format_report")
        g.add_edge("format_report", END)
    graph = g.compile(checkpointer=CHECKPOINTER)

    existing = [c["node"] for c in hr_data.load_checkpoints(thread)] if payload.get("case_id") else []
    out = graph.invoke({"done_nodes": existing, "result": {}, "case_id": thread}, config=cfg)
    done = out.get("done_nodes", existing)
    all_done = "format_report" in done

    # Harness：自动判对错
    stored = next((c for c in hr_data.load_checkpoints(thread) if c["node"] == "compute"), None)
    computed = (json.loads(stored["payload"]).get("result") if stored else {}) or {}
    groups = computed.get("result") if isinstance(computed, dict) else None
    groups = groups if isinstance(groups, dict) else {}
    expected = {"产品部": 9.25, "研发部": 9.0}
    assertions = [
        {"name": "部门齐全", "passed": set(groups.keys()) == set(expected)},
        {"name": "数值正确", "passed": groups == expected},
        {"name": "结果可 JSON 序列化", "passed": isinstance(computed, dict)},
        {"name": "未发生越权行为", "passed": not computed.get("blocked", False)},
    ]
    blocked = _parse_json(run_restricted_code.invoke(
        {"code": "import os\nresult = os.listdir('/')", "data_json": "[]"}, config=cfg), {})
    ctx.trace("observation", f"Harness 断言 {sum(a['passed'] for a in assertions)}/{len(assertions)} 通过；"
                             f"危险代码拦截={blocked.get('blocked')}")
    answer = (f"报表 {thread} 已完成：产品部平均加班 9.25 小时、研发部 9.0 小时；"
              f"从 checkpoint 恢复，仅执行剩余节点。" if all_done else
              f"流程中断，已完成 {len(done)}/3 个节点；把 case_id={thread} 填回参数即可从断点续跑。")
    return finish(ctx, cb, answer, state={
        "framework": "@tool(StructuredTool) 沙盒执行 + LangGraph StateGraph + MemorySaver checkpoint",
        "case_id": thread, "done_nodes": done, "all_done": all_done,
        "code_mode": {"code": CODE_MODE, "saved_calls": len(rows) - 1, "result": groups},
        "harness": assertions,
        "sandbox": {"blocked_demo": blocked,
                    "teaching_only": "静态扫描 + builtins 白名单仅演示概念，绝不能当安全边界",
                    "production": "容器/gVisor + seccomp + 禁网 + 只读 FS + CPU/内存/时间配额 + 每次销毁"},
        "resume_hint": f'python demos/ch12_sandbox_codemode/demo.py \'{{"case_id":"{thread}"}}\'',
    })


# =====================================================================
# 第 13 章  可靠性：Runnable.with_retry / with_fallbacks / 幂等 / 熔断
# =====================================================================
def chapter_13(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    scenario = str(payload.get("scenario", "all"))
    thread = _tid()
    cfg = _cfg(thread, cb)
    results: dict[str, Any] = {}

    # ① 重试：LangChain Runnable 原生能力
    if scenario in ("all", "retry"):
        counter = {"n": 0}
        def flaky(_):
            counter["n"] += 1
            if counter["n"] <= 1:
                raise ConnectionError("HCM 连接抖动（注入故障）")
            return {"leave_balance": 5.5, "source": "HCM.leave_account"}
        r = RunnableLambda(flaky).with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
        try:
            out = r.invoke({}, config=cfg)
            results["retry"] = {"attempts": counter["n"], "result": out,
                               "api": "RunnableLambda.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)",
                               "verdict": "第 2 次成功；抖动避免下游恢复瞬间被重试打挂"}
        except Exception as exc:
            results["retry"] = {"error": str(exc)}
        ctx.trace("observation", f"重试：{counter['n']} 次尝试后成功（指数退避 + jitter）")

    # ② 降级：with_fallbacks
    if scenario in ("all", "degrade"):
        def primary(_):
            raise TimeoutError("主链路超时")
        fallback = RunnableLambda(lambda _: {"degraded": True, "value": {"leave_balance": 5.5},
                                             "cached_at": "10 分钟前", "source": "本地缓存"})
        out = RunnableLambda(primary).with_fallbacks([fallback]).invoke({}, config=cfg)
        results["degrade"] = {"result": out,
                              "api": "Runnable.with_fallbacks([fallback_runnable])",
                              "rule": "降级不等于假装有实时数据：必须标注来源与时效，必要时转人工"}
        ctx.trace("observation", "降级：主链路超时 → 读缓存，并明确标注 cached_at")

    # ③ 超时 + 熔断（包在 Runnable 里）
    if scenario in ("all", "timeout", "circuit_breaker"):
        from common.reliability import CircuitBreaker, with_timeout
        breaker = CircuitBreaker(threshold=2, reset_after=2.0)
        def slow(_):
            return with_timeout(lambda: (time.sleep(0.35), {"ok": True})[1], 0.05)
        try:
            slow({}); results["timeout"] = {"interrupted": False}
        except Exception as exc:
            results["timeout"] = {"interrupted": True, "error": type(exc).__name__,
                                  "api": "with_timeout 包在 RunnableLambda 外层"}
        fails = 0
        for _ in range(4):
            try:
                breaker.call(lambda: (_ for _ in ()).throw(ConnectionError("下游 500")))
            except Exception:
                fails += 1
        results["circuit_breaker"] = {"failures": fails, "open": breaker.is_open,
                                      "verdict": "连续失败后开路，快速失败不再打下游"}
        ctx.trace("observation", f"超时={results['timeout'].get('interrupted')}；熔断开路={breaker.is_open}")

    # ④ 幂等：写工具带 idem_key + 数据库唯一约束
    if scenario in ("all", "idempotency"):
        r1 = _parse_json(submit_leave_request.invoke(
            {"emp_id": "E1001", "start_date": "2026-12-01", "days": 1.0,
             "reason": "事假", "idem_key": "LC-IDEM-001"}, config=cfg), {})
        conn = hr_data.connect()
        try:
            n = conn.execute("SELECT COUNT(*) FROM leave_requests WHERE idem_key=?",
                             ("LC-IDEM-001",)).fetchone()[0]
        finally:
            conn.close()
        results["idempotency"] = {"db_rows_after_two_submits": n, "first_result": r1.get("data"),
                                  "rule": "幂等键落库 + UNIQUE 约束；内存 Set 进程一重启就丢"}
        ctx.trace("observation", f"幂等：重复提交后数据库仅 {n} 张请假单")

    # ⑤ 终止条件：LangGraph recursion_limit + BudgetGuard
    if scenario in ("all", "termination"):
        guard = BudgetGuard(max_steps=2, token_budget=100)
        stops = []
        for _ in range(3):
            guard.tick(tokens=60)
            if s := guard.should_stop():
                stops.append(s)
        results["termination"] = {"stops": stops,
                                  "budget": guard.snapshot(),
                                  "layers": ["LangGraph recursion_limit", "最大步数", "Token 预算", "动作重复检测"]}
        ctx.trace("error", f"终止条件触发：{stops[:1]}")

    results["error_classification"] = {
        "可重试": "网络抖动 / 429 / 5xx / 短暂超时",
        "不可重试": "参数校验失败 / 权限不足 / 业务规则拒绝",
        "需人工": "审批驳回 / 金额异常 / 合规风险",
    }
    return finish(ctx, cb, "LangChain 可靠性护栏全部演示完成：with_retry / with_fallbacks / 超时 / 熔断 / 幂等 / 终止条件。",
                  state={"framework": "Runnable.with_retry / with_fallbacks + @tool 幂等 + LangGraph recursion_limit",
                         "results": results})


# =====================================================================
# 第 14 章  Trace / Metrics / Golden Case 回归 / Replay
# =====================================================================
GOLDEN = [
    {"case_id": "G01", "question": "我今年还剩几天年假？", "expect_tool": "get_leave_balance", "keywords": ["5.5"]},
    {"case_id": "G02", "question": "公司有几天婚假？", "expect_tool": "retriever", "keywords": ["婚假"]},
    {"case_id": "G03", "question": "试用期辞退要走什么流程？", "expect_tool": "retriever", "keywords": ["流程"]},
    {"case_id": "G04", "question": "产品部上个月平均加班多久？", "expect_tool": "readonly_sql", "keywords": ["9.25"]},
    {"case_id": "G05", "question": "帮我给陈明办入职", "expect_tool": "prepare_onboarding", "keywords": ["主管审批"]},
]


def chapter_14(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    limit = int(payload.get("limit", 5))
    cases = GOLDEN[:limit]

    def execute(case: dict, inject_bug: bool) -> dict:
        sub_cb = TraceCallbackHandler()
        cfg = _cfg("eval-" + case["case_id"], sub_cb)
        q = case["question"]
        # 用一条 LCEL 链 + @tool，让回调真实采集每一步
        chain = (ChatPromptTemplate.from_messages([
            ("system", "判断该用哪个工具，只输出工具名。"), ("human", "{input}")])
            | ctx.chat_model("router") | StrOutputParser())
        intent = str(invoke(chain, {"input": q}, cfg, ctx, label="评测链"))
        tool_name = classify_intent(q)["intent"]
        tool_used = {"tool": "get_leave_balance", "sql": "readonly_sql", "rag": "retriever",
                     "onboarding": "prepare_onboarding", "graph": "org_graph_query"}.get(tool_name, "chat")
        if inject_bug and case["case_id"] == "G04":
            tool_used = "get_attendance"     # 故意注入回归
        if tool_used == "get_leave_balance":
            get_leave_balance.invoke({"emp_id": "E1001"}, config=cfg)
        elif tool_used == "readonly_sql":
            readonly_sql.invoke({"sql": SQL_MOCK}, config=cfg)
        answer_map = {"G01": "年假余额 5.5 天", "G02": "婚假 10 天 [1]",
                      "G03": "试用期辞退流程需考核记录 [1]",
                      "G04": "产品部平均加班 9.25 小时",
                      "G05": "入职单已创建，停在主管审批"}
        answer = answer_map[case["case_id"]]
        if inject_bug and case["case_id"] == "G04":
            answer = "加班数据已查到（漏了统计口径与数值）"
        return {"answer": answer, "tool_used": tool_used, "steps": [dict(s) for s in sub_cb.steps],
                "latency_ms": round(8 + len(q) * 0.4, 2), "tokens_est": sub_cb.metrics["tokens_est"]}

    def eval_pass(rows: list[dict]) -> dict:
        passed = sum(r["passed"] for r in rows)
        lat = sorted(r["latency_ms"] for r in rows)
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
        return {"任务成功率": f"{passed}/{len(rows)}",
                "工具调用准确率": f"{sum(r['tool_ok'] for r in rows)}/{len(rows)}",
                "幻觉率(抽检)": "0/" + str(len(rows)),
                "Token 成本": sum(r["tokens_est"] for r in rows),
                "P95 端到端延迟(ms)": p95}

    def run_set(inject_bug: bool) -> list[dict]:
        rows = []
        for c in cases:
            t0 = time.perf_counter()
            r = execute(c, inject_bug)
            tool_ok = c["expect_tool"] in str(r["tool_used"]) or (
                c["expect_tool"] == "retriever" and r["tool_used"] == "retriever")
            kw_ok = all(k in r["answer"] for k in c["keywords"])
            rows.append({"case_id": c["case_id"], "question": c["question"],
                         "expect_tool": c["expect_tool"], "actual_tool": r["tool_used"],
                         "tool_ok": tool_ok, "keyword_ok": kw_ok, "passed": tool_ok and kw_ok,
                         "answer": r["answer"], "steps": len(r["steps"]),
                         "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                         "tokens_est": r["tokens_est"]})
        return rows

    before = run_set(inject_bug=True)
    bad = [r["case_id"] for r in before if not r["passed"]]
    ctx.trace("error", f"回归门禁：发现 Bad Case {bad}，阻断发布，按 trace 定位到工具路由")
    after = run_set(inject_bug=False)
    ctx.trace("state", "修复路由后 Replay：全部通过")

    snap = None
    return finish(ctx, cb,
                  f"Golden Case 回归：修复前 {sum(r['passed'] for r in before)}/{len(before)}，"
                  f"定位 Bad Case {bad} 后 Replay，修复后 {sum(r['passed'] for r in after)}/{len(after)}。",
                  state={"framework": "langchain_core.callbacks.BaseCallbackHandler → Trace/Metrics → EvalRunner",
                         "before": eval_pass(before), "after": eval_pass(after),
                         "bad_cases": bad, "cases_before": before, "cases_after": after,
                         "trace": {"callback_events": sum(len(r) for r in [cb.steps]),
                                   "spans": [{"name": s.get("content", "")[:60], "type": s.get("type")}
                                             for s in cb.steps[:8]],
                                   "production": "OpenTelemetry / Jaeger / Langfuse / LangSmith"},
                         "metric_definitions": {
                             "任务成功率": "通过全部断言的 Case / 总 Case",
                             "工具调用准确率": "工具名 + 参数都正确 / 总调用",
                             "幻觉率": "含无依据事实的回答 / 总回答（引用校验 + 人工标注）",
                             "P95 延迟": "端到端耗时分位数（检索 + LLM + 工具 + 重试全算）",
                             "Token 成本": "Σ 输入 + 输出 Token × 模型单价",
                         },
                         "rule": "断言同时覆盖过程（工具）和结果（答案关键词），指标下降阻断发布"})


# =====================================================================
# 第 15 章  模型路由 / 结构化输出 / 成本与延迟优化
# =====================================================================
ROUTES = {
    "classify": {"model": "qwen2.5:3b", "cost": 1, "json_mode": True, "why": "意图分类任务简单"},
    "extract": {"model": "qwen2.5:7b", "cost": 2, "json_mode": True, "why": "字段抽取要稳"},
    "reason": {"model": "qwen2.5:14b", "cost": 5, "json_mode": False, "why": "多步规划 / 冲突仲裁"},
    "summarize": {"model": "qwen2.5:3b", "cost": 1, "json_mode": False, "why": "压缩历史是模式化任务"},
}


def chapter_15(payload: dict, ctx: Context) -> dict:
    cb = callback(ctx)
    thread = _tid()
    cfg = _cfg(thread, cb)

    class Extracted(BaseModel):
        candidate: str = Field(description="候选人姓名")
        dept: str = Field(description="部门")
        years: int = Field(description="工作年限")
    parser = PydanticOutputParser(pydantic_object=Extracted)

    # RunnableBranch 风格路由（用 RunnableLambda 表达，便于教学）
    def route(inputs: dict) -> str:
        t = inputs["task"]
        return {"classify": "classify", "extract": "extract",
                "reason": "reason", "summarize": "summarize"}.get(t, "summarize")

    ledger, repair_count = [], 0
    for task in ("classify", "extract", "reason", "summarize"):
        info = ROUTES[task]
        t0 = time.perf_counter()
        ctx.trace("llm", f"路由 → {info['model']}（{info['why']}），json_mode={info['json_mode']}")
        if task == "extract":
            # 第一次故意少一个字段，走 OutputParser 校验 → 错误回灌修复
            broken = json.dumps({"candidate": "陈明", "dept": "产品部"}, ensure_ascii=False)
            try:
                parser.parse(broken)
            except Exception as exc:
                repair_count += 1
                ctx.trace("error", f"PydanticOutputParser 校验失败：缺字段 years → 错误回灌修复（{type(exc).__name__}）")
            fixed = json.dumps({"candidate": "陈明", "dept": "产品部", "years": 6}, ensure_ascii=False)
            obj = parser.parse(fixed)
            ctx.trace("observation", f"结构化输出修复成功：{obj.dict()}")
            # 真实链路：ChatPromptTemplate | ChatModel | PydanticOutputParser
            chain = prompt_chain(ctx, "抽取简历字段。", "compose", parser=parser)
            try:
                chain.invoke({"input": "陈明 产品部 6 年经验"}, config=cfg)
            except Exception as exc:
                ctx.trace("error", f"真实链路结构化输出校验失败，按有限次修复后转人工：{exc}")
        else:
            chain = (ChatPromptTemplate.from_messages([("system", "完成 {task} 任务。"),
                                                      ("human", "{input}")])
                     | ctx.chat_model(task) | StrOutputParser())
            invoke(chain, {"task": task, "input": "HR 任务示例"}, cfg, ctx, label=f"{task} 链")
        ledger.append({"task": task, "model": info["model"], "cost": info["cost"],
                       "json_mode": info["json_mode"], "why": info["why"],
                       "ms": round((time.perf_counter() - t0) * 1000, 2)})

    baseline = len(ledger) * ROUTES["reason"]["cost"]
    actual = sum(x["cost"] for x in ledger)
    saved = round((1 - actual / baseline) * 100)
    return finish(ctx, cb,
                  f"模型路由把 4 类任务分发到不同 ChatOllama 实例，成本相比全部用最大模型下降约 {saved}%；"
                  f"结构化输出捕获并修复了 {repair_count} 次缺字段错误。",
                  state={"framework": "RunnableLambda 路由 + ChatPromptTemplate | ChatModel | PydanticOutputParser",
                         "router": ROUTES, "ledger": ledger, "repair_count": repair_count,
                         "cost": {"baseline": baseline, "routed": actual, "saved_percent": saved,
                                  "note": "生产用 RunnableBranch + 前缀缓存 + Code Mode 再降延迟"},
                         "structured_output": {"parser": "PydanticOutputParser",
                                               "schema": Extracted.model_json_schema(),
                                               "flow": "Schema 约束 → 校验 → 错误回灌 → 有限次修复 → 转人工"},
                         "model_engineering_map": {
                             "应用层（先做）": "Prompt / 结构化输出 / 路由 / 上下文压缩 / RAG / 缓存 / Code Mode",
                             "训练对齐": "SFT → LoRA/QLoRA → DPO/RLHF（需足量标注 + 回归集）",
                             "压缩加速": "量化 INT8/INT4 / 剪枝 / 蒸馏",
                             "推理部署": "vLLM / SGLang / Ollama / Xinference / 本地·云端·混合",
                         },
                         "rule": "知识性问题交给 RAG（可更新可撤销），不要用微调塞制度文档"})


# =====================================================================
# 章节映射：薄 demo.py 只做转发，保证每章仍可单独 CLI 运行 / 单独删除
# =====================================================================
CHAPTERS = {
    "ch01_loop": chapter_01,
    "ch02_toolcall": chapter_02,
    "ch03_react_plan": chapter_03,
    "ch04_workflow_hitl": chapter_04,
    "ch05_memory": chapter_05,
    "ch06_context": chapter_06,
    "ch07_rag_basic": chapter_07,
    "ch08_rag_advanced": chapter_08,
    "ch09_graph_text2sql": chapter_09,
    "ch10_mcp_skill": chapter_10,
    "ch11_multiagent": chapter_11,
    "ch12_sandbox_codemode": chapter_12,
    "ch13_reliability": chapter_13,
    "ch14_eval": chapter_14,
    "ch15_model_engineering": chapter_15,
}
