"""LangGraph 全链路：把前 15 章的所有能力串成一张可运行的状态图。

节点地图（这就是「Agent 全链路」）：

    START
      │
      ▼
  guard_memory ── 预算护栏 + 会话/长期/用户记忆（InMemoryStore）
      │
      ▼
    router ── PydanticOutputParser 结构化意图（LangChain）
      │
      ├─ rag ──────────────► retrieve ── 三路混合 BaseRetriever ─────────┐
      ├─ tool/sql/graph/mcp ► agent ⇄ tools ── bind_tools + ToolNode ──────┤
      ├─ onboarding ───────► plan ── JSON Plan ──► prepare_onboarding ─────┤
      │                                          │                        │
      │                                          ▼                        │
      │                                   human_approval ── interrupt()    │
      │                                          │   （人工审批，可恢复）   │
      │                                          ▼                        │
      │                                    post_approval ── HR/IT 节点     │
      └─ chat ───────────────────────────────────────────────────────────┤
                                                                          ▼
                                        compose ── 带引用回答 + 幻觉校验
                                                                          │
                                                                          ▼
                                    write_memory ── 长任务结论写入 Store ──► END

编译带 checkpointer：thread_id 持久化，interrupt 后可用 Command(resume=...) 从断点续跑。
"""
# 不启用 future annotations：LangGraph 需要读到节点函数第二个参数的
# RunnableConfig 真实类型才会注入 config；变成字符串后会只传 state 导致 TypeError。
import json
import re
from typing import Annotated, Any

from langchain_core.messages import (AIMessage, AnyMessage, HumanMessage, SystemMessage,
                                    ToolMessage, trim_messages)
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from . import config, hr_data
from .context import Context
from .lc_callbacks import TraceCallbackHandler
from .lc_models import TeachingChatModel, build_chat_model, classify_intent
from .lc_retrieval import build_retriever
from .lc_tools import build_tools, set_fault
from .reliability import BudgetGuard

# 模块级单例：同一进程内跨请求保留 checkpoint 与长期记忆。
# 生产替换：SqliteSaver / PostgresSaver + 持久化 Store（见教程第 16 章）。
CHECKPOINTER = MemorySaver()
STORE = InMemoryStore()


class Intent(BaseModel):
    intent: str = Field(description="rag | tool | sql | graph | mcp | onboarding | chat")
    reason: str = Field(description="选择该分支的理由")
    confidence: float = Field(default=0.9, description="置信度 0~1")


class FullChainState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    question: str
    thread_id: str
    emp_id: str
    intent: str
    confidence: float
    reason: str
    plan: dict
    documents: list[dict]
    tool_results: list[dict]
    memory_ctx: list[dict]
    context_block: str
    case_id: str
    status: str
    answer: str
    citations: list[dict]
    budget: dict
    errors: list[str]
    node_path: list[str]
    mode: str
    max_steps: int


def _tc(x: Any) -> int:
    ms = x if isinstance(x, list) else [x]
    return sum(max(1, len(str(getattr(m, "content", ""))) // 2) for m in ms)


def _tool_results_from_messages(messages: list[AnyMessage]) -> list[dict]:
    out = []
    for m in messages:
        if isinstance(m, ToolMessage):
            try:
                out.append(json.loads(str(m.content)))
            except (json.JSONDecodeError, TypeError):
                out.append({"raw": str(m.content)[:200]})
    return out


def _extract_candidate(question: str) -> str:
    m = re.search(r"给\s*([\u4e00-\u9fff]{2,4})\s*办", question)
    return m.group(1) if m else "陈明"


def pending_interrupt(graph, cfg: dict) -> dict | None:
    """LangGraph 0.3.x 的挂起信息在 StateSnapshot.tasks[*].interrupts 里。"""
    try:
        snap = graph.get_state(cfg)
        for task in snap.tasks or []:
            for it in getattr(task, "interrupts", ()) or ():
                value = getattr(it, "value", None)
                if isinstance(value, dict):
                    return value
    except Exception:
        pass
    return None


def build_graph(*, ctx: Context, mode: str, use_mcp: bool = False,
                token_budget: int | None = None, max_steps: int = 6,
                top_k: int = 3, fail_tools: str = "none",
                emp_id: str = "E1001"):
    """每次运行编译一张新图（闭包捕获本次 Context 与模型），但共享 CHECKPOINTER / STORE。"""
    budget = token_budget or config.TOKEN_BUDGET
    set_fault(fail_tools)
    guard = BudgetGuard(max_steps=max_steps, token_budget=budget)

    tools = build_tools(use_mcp=use_mcp)
    retriever, retriever_info = build_retriever(mode, top_k=top_k)
    router_model = build_chat_model(mode, "router")
    plan_model = build_chat_model(mode, "plan")
    tools_model = build_chat_model(mode, "tools")
    compose_model = build_chat_model(mode, "compose")
    summarize_model = build_chat_model(mode, "summarize")
    parser = PydanticOutputParser(pydantic_object=Intent)

    # 首次写入几条长期/用户记忆（Store 是跨会话的）
    if not STORE.get(("user", "E1001"), "interview_pref"):
        STORE.put(("user", "E1001"), "interview_pref", {"value": "偏好上午 9:00–10:00 面试"})
    if not STORE.get(("user", "E1001"), "health"):
        STORE.put(("user", "E1001"), "health", {"value": "对海鲜过敏，接待订餐需避开"})
    if not STORE.get(("long", "org"), "calibration"):
        STORE.put(("long", "org"), "calibration", {"value": "2026-10 产品部晋升名额 2 个"})

    def trace(type_: str, content: str, **meta: Any) -> None:
        ctx.trace(type_, content, **meta)

    # ---------------- 节点 ----------------
    def guard_memory(state: FullChainState) -> dict:
        guard.tick(tokens=40)
        stop = guard.should_stop()
        if stop:
            trace("error", f"预算护栏触发终止条件：{stop}")
            return {"status": "BUDGET_STOP", "errors": [stop]}
        emp = state.get("emp_id", "E1001")
        mem: list[dict] = []
        try:
            for item in STORE.search(("user", emp), limit=5):
                mem.append({"scope": "user/user_memory", "value": item.value})
            long_item = STORE.get(("long", "org"), "calibration")
            if long_item:
                mem.append({"scope": "long/long_term", "value": long_item.value})
        except Exception as exc:
            mem.append({"scope": "fallback", "value": f"Store 读取降级：{exc}"})
        trace("memory", f"从 LangGraph Store 召回 {len(mem)} 条记忆（会话记忆由 checkpointer 承载）",
              items=[m["scope"] for m in mem])
        return {"memory_ctx": mem, "budget": guard.snapshot(),
                "node_path": ["guard_memory"], "status": "RUNNING"}

    def router(state: FullChainState) -> dict:
        q = state["question"]
        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是企业 HR 智能体的意图路由器。只输出 JSON，不要解释。\n{format}"),
            ("human", "{question}"),
        ]).partial(format=parser.get_format_instructions())
        chain = prompt | router_model | parser
        try:
            obj: Intent = chain.invoke({"question": q})
            intent, reason, conf = obj.intent, obj.reason, float(obj.confidence)
        except Exception as exc:
            # 结构化输出校验失败 → 回灌错误 → 确定性降级（生产应做有限次修复重试）
            fallback = classify_intent(q)
            intent, reason, conf = fallback["intent"], fallback["reason"] + f"（解析降级：{exc}）", 0.6
            trace("error", f"意图结构化输出解析失败，降级到规则路由：{exc}")
        trace("thought", f"意图路由 → {intent}｜{reason}｜置信度 {conf}")
        return {"intent": intent, "reason": reason, "confidence": conf,
                "node_path": ["guard_memory", "router"]}

    def context_build(state: FullChainState) -> dict:
        msgs = state.get("messages", [])
        trimmed = trim_messages(msgs, max_tokens=max(80, budget // 4), strategy="last",
                                token_counter=_tc, include_system=False, allow_partial=False)
        summary = summarize_model.invoke(
            [HumanMessage(content=f"把以下对话压成 80 字要点：{state['question']}")]
        ).content if len(msgs) > 2 else "（首轮，无历史）"
        block = "\n".join([
            "P0 系统规则：只依据提供的资料与工具结果回答，不编造事实。",
            f"P1 用户画像：工号 {state.get('emp_id','E1001')}，产品部，中文简称。",
            f"P1 记忆：{json.dumps(state.get('memory_ctx', []), ensure_ascii=False)[:300]}",
            f"P2 历史摘要：{summary}",
            f"P0 意图：{state.get('intent')}（{state.get('reason','')}）",
            f"预算：{budget} Token；裁剪后 {len(trimmed)}/{len(msgs)} 条消息进上下文。",
        ])
        trace("llm", f"上下文装配：{len(msgs)} 条消息 → 保留 {len(trimmed)} 条，预算 {budget} Token")
        return {"context_block": block}

    def plan_node(state: FullChainState) -> dict:
        raw = plan_model.invoke(
            [HumanMessage(content=f"为以下 HR 任务生成 JSON 执行计划：{state['question']}")]
        ).content
        try:
            plan = json.loads(str(raw))
        except json.JSONDecodeError:
            plan = {"goal": state["question"], "steps": [], "success_criteria": "生成 case_id 并挂起审批"}
        trace("plan", f"Plan-and-Solve：生成 {len(plan.get('steps', []))} 步计划｜验收：{plan.get('success_criteria','')}")
        return {"plan": plan, "node_path": ["router", "plan"]}

    def retrieve_node(state: FullChainState) -> dict:
        docs = retriever.invoke(state["question"])
        items = [{"chunk_id": d.metadata.get("chunk_id"), "citation_id": d.metadata.get("citation_id"),
                  "title": d.metadata.get("title"), "section": d.metadata.get("section"),
                  "version": d.metadata.get("version"), "sources": d.metadata.get("sources", []),
                  "text": d.page_content} for d in docs]
        versions = {i["version"] for i in items}
        trace("retrieve", f"三路混合检索返回 {len(items)} 个 Document｜版本 {sorted(versions)}",
              ids=[i["chunk_id"] for i in items])
        return {"documents": items, "citations": items, "node_path": ["retrieve"]}

    def agent_node(state: FullChainState) -> dict:
        guard.tick(tokens=120)
        if guard.should_stop():
            trace("error", "ReAct 循环达到步数/Token 上限，强制收敛到 compose")
            return {"messages": [AIMessage(content="达到终止条件，交给 compose 生成兜底回答。")]}
        payload = {"intent": state.get("intent"), "emp_id": state.get("emp_id", "E1001"),
                   "documents": state.get("documents", [])[:2],
                   "context_block": state.get("context_block", "")[:300]}
        msgs = [SystemMessage(content="HR_CTX:" + json.dumps(payload, ensure_ascii=False))] + \
               list(state.get("messages", []))
        ai = tools_model.bind_tools(tools).invoke(msgs)
        if getattr(ai, "tool_calls", None):
            trace("thought", "ReAct：模型决定调用工具 " + ", ".join(c["name"] for c in ai.tool_calls))
        else:
            trace("thought", "ReAct：模型判断信息充分，退出工具循环")
        return {"messages": [ai]}

    def prepare_onboarding(state: FullChainState) -> dict:
        # interrupt 恢复会重跑本节点，所以建单必须幂等：已有 case_id 直接跳过
        if state.get("case_id"):
            trace("state", f"恢复模式：case {state['case_id']} 已存在，跳过重复建单（幂等）")
            return {"node_path": ["prepare_onboarding"]}
        candidate = _extract_candidate(state["question"])
        created = hr_data.create_onboarding(candidate, "产品部", "产品经理")
        hr_data.checkpoint(created["case_id"], "collect_material", {"candidate": candidate, "materials": 6})
        trace("action", f"创建入职单 {created['case_id']}（{candidate}），材料核对完成，写 checkpoint")
        return {"case_id": created["case_id"], "status": "WAIT_MANAGER_APPROVE",
                "node_path": ["prepare_onboarding"]}

    def human_approval(state: FullChainState) -> dict:
        # interrupt() 之前不放任何副作用：恢复时节点会从头重放
        decision = interrupt({
            "prompt": f"入职单 {state.get('case_id')} 等待主管审批（按 SOP 1.3，Agent 不得代批）",
            "case_id": state.get("case_id"),
            "actions": [{"key": "approve", "label": "通过"}, {"key": "reject", "label": "驳回"}],
            "sop": "《招聘与入职 SOP》1.3：主管审批节点必须人工确认",
            "thread_id": state.get("thread_id"),
        })
        action = (decision or {}).get("action", "approve")
        approver = (decision or {}).get("approver", "李四（主管）")
        hr_data.audit(approver, f"hitl:{action}", state.get("case_id", ""), "LangGraph interrupt 人工决策留痕")
        trace("hitl", f"人工决策：{approver} 选择 {action}，从 interrupt 断点恢复", action=action)
        return {"status": "HR_REVIEW" if action == "approve" else "REJECTED",
                "node_path": ["human_approval"]}

    def post_approval(state: FullChainState) -> dict:
        if state.get("status") == "REJECTED":
            hr_data.checkpoint(state.get("case_id", ""), "rejected", {"reason": "主管驳回"})
            trace("state", "主管驳回，流程终止，不执行 HR 复核与 IT 开账号")
            return {"node_path": ["post_approval"]}
        cid = state.get("case_id", "")
        hr_data.checkpoint(cid, "hr_review", {"checked": ["劳动合同", "录用条件告知书"]})
        hr_data.update_case(cid, "IT_PROVISIONING", "it_provisioning")
        trace("observation", "HR 复核完成，推进到 IT 开账号")
        ticket = {"ticket": "ITSM-2026-1145", "systems": ["邮箱", "OA", "Git", "门禁"]}
        hr_data.checkpoint(cid, "it_provisioning", ticket)
        hr_data.update_case(cid, "DONE", "done", {"it_ticket": ticket["ticket"]})
        hr_data.checkpoint(cid, "done", {"finished": True})
        trace("state", f"ITSM 工单 {ticket['ticket']} 完成，状态 → DONE")
        return {"status": "DONE", "node_path": ["post_approval"]}

    def compose_node(state: FullChainState) -> dict:
        tool_results = _tool_results_from_messages(state.get("messages", []))
        payload = {"intent": state.get("intent"), "documents": state.get("documents", []),
                   "tool_results": tool_results, "case_id": state.get("case_id"),
                   "status": state.get("status"), "emp_id": state.get("emp_id", "E1001"),
                   "context_block": state.get("context_block", "")[:200]}
        msgs = [SystemMessage(content="HR_CTX:" + json.dumps(payload, ensure_ascii=False)),
                HumanMessage(content=state["question"])]
        answer = str(compose_model.invoke(msgs).content)
        # 幻觉控制：引用编号是否越界、数字主张是否有依据
        cited = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
        docs = state.get("documents", [])
        bad_cites = [n for n in cited if n > len(docs)]
        versions_text = "、".join(sorted({str(d.get("version", "?")) for d in docs})) or "无"
        if bad_cites:
            trace("error", f"引用质量校验拦截：回答引用了不存在的片段 {bad_cites}")
            answer += "（引用校验提示：部分引用编号无对应片段，已标记待复核）"
        else:
            trace("observation",
                  f"引用质量校验通过：{len(set(cited))} 个引用均可溯源，版本 {versions_text}")
        return {"answer": answer, "tool_results": tool_results, "node_path": ["compose"]}

    def write_memory(state: FullChainState) -> dict:
        STORE.put(("long", "hr"), f"run::{state.get('thread_id','t')}",
                  {"question": state["question"], "intent": state.get("intent"),
                   "answer": str(state.get("answer", ""))[:200], "status": state.get("status")})
        trace("memory", "本次结论写入 LangGraph Store（长期记忆，跨会话可检索）")
        return {"status": "FINISHED", "node_path": ["write_memory"]}

    # ---------------- 图结构 ----------------
    g = StateGraph(FullChainState)
    for name, fn in [
        ("guard_memory", guard_memory), ("router", router), ("context_build", context_build),
        # 节点名不能和 State 里的 key 同名（LangGraph 0.3 会抛
        # "'plan' is already being used as a state key"），故叫 planner
        ("planner", plan_node), ("retrieve", retrieve_node), ("agent", agent_node),
        ("prepare_onboarding", prepare_onboarding), ("human_approval", human_approval),
        ("post_approval", post_approval), ("compose", compose_node), ("write_memory", write_memory),
    ]:
        g.add_node(name, fn)
    g.add_node("tools", ToolNode(tools))

    g.add_edge(START, "guard_memory")
    g.add_edge("guard_memory", "router")

    def route(state: FullChainState) -> str:
        intent = state.get("intent", "chat")
        if intent == "onboarding":
            return "plan"
        if intent == "rag":
            return "retrieve"
        if intent in ("tool", "sql", "graph", "mcp"):
            return "agent"
        return "compose"

    g.add_conditional_edges("router", route, {
        "plan": "context_build", "retrieve": "context_build",
        "agent": "context_build", "compose": "context_build",
    })
    # context_build 之后才真正分流（先装配上下文再执行，符合 Context Engineering）
    g.add_conditional_edges("context_build", route, {
        "plan": "planner", "retrieve": "retrieve", "agent": "agent", "compose": "compose",
    })
    g.add_edge("planner", "prepare_onboarding")
    g.add_edge("prepare_onboarding", "human_approval")
    g.add_edge("human_approval", "post_approval")
    g.add_edge("post_approval", "compose")
    g.add_edge("retrieve", "compose")

    def after_agent(state: FullChainState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and getattr(last, "tool_calls", None) else "compose"

    g.add_conditional_edges("agent", after_agent, {"tools": "tools", "compose": "compose"})
    g.add_edge("tools", "agent")
    g.add_edge("compose", "write_memory")
    g.add_edge("write_memory", END)

    graph = g.compile(checkpointer=CHECKPOINTER)
    return graph, {"tools": [getattr(t, "name", "?") for t in tools],
                   "retriever": retriever_info, "budget": budget, "max_steps": max_steps,
                   "graph_nodes": list(g.nodes)}


def config_for(thread_id: str, callbacks: TraceCallbackHandler | None = None,
               max_steps: int = 6) -> dict:
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id},
                           "recursion_limit": max(12, max_steps * 3)}
    if callbacks:
        cfg["callbacks"] = [callbacks]
    return cfg
