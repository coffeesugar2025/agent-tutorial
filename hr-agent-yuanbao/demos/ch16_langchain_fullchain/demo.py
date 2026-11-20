"""第 16 章 · LangChain / LangGraph 全链路 Demo（统一契约入口）

前 15 章是「每章独立小 Demo」；这一章把它们**串成一条真正跑得通的生产链路**：
意图路由 → 上下文装配 → Planning / ReAct 工具循环 / 三路混合检索 / 状态机+人工审批
→ 带引用回答与幻觉校验 → 长期记忆写入 → Trace/Metrics 全量采集。

运行：
  python demos/ch16_langchain_fullchain/demo.py
  python demos/ch16_langchain_fullchain/demo.py '{"scenario":"onboarding"}'
  python demos/ch16_langchain_fullchain/demo.py '{"scenario":"mcp"}'
  python demos/ch16_langchain_fullchain/demo.py '{"scenario":"eval"}'
审批恢复：
  python demos/ch16_langchain_fullchain/demo.py '{"thread_id":"...","action":"approve"}'

依赖：pip install -r requirements-langchain.txt
没装也不会让后端崩：run() 会返回一份带安装提示的契约结果。
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.context import Context

try:
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    from common.lc_callbacks import TraceCallbackHandler
    from common.lc_graph import build_graph, config_for, pending_interrupt
    LC_AVAILABLE = True
    LC_IMPORT_ERROR = ""
except ImportError as exc:          # 没装可选依赖时优雅降级
    LC_AVAILABLE = False
    LC_IMPORT_ERROR = str(exc)

SCENARIOS = {
    "leave": "我今年还剩几天年假？",
    "policy": "公司有几天婚假？",
    "termination": "试用期辞退员工要走什么流程？",
    "sql": "产品部上个月平均加班多久？",
    "graph": "谁和张三在同一个项目，张三向谁汇报？",
    "onboarding": "帮我给新员工陈明办理入职，并同步进度",
    "mcp": "通过 MCP 查一下我今年还剩几天年假？",
    "chat": "你好，你能做什么？",
}

EXPECT = {
    "leave": ("tool", "5.5", "工具查询"),
    "policy": ("rag", "婚假", "RAG 制度问答"),
    "sql": ("sql", "9.25", "Text2SQL"),
    "graph": ("graph", "三元组", "图谱检索"),
    "onboarding": ("onboarding", "主管审批", "状态机 + HITL"),
}


def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def _params(payload: dict) -> dict:
    return {
        "use_mcp": _as_bool(payload.get("use_mcp", False)),
        "token_budget": int(payload.get("token_budget", 3000)),
        "max_steps": int(payload.get("max_steps", 6)),
        "top_k": int(payload.get("top_k", 3)),
        "fail_tools": str(payload.get("fail_tools", "none")),
        "emp_id": str(payload.get("emp_id", "E1001")),
    }


def _assemble(ctx: Context, cb: TraceCallbackHandler, out: dict, meta: dict,
              thread_id: str, hitl: dict | None = None) -> dict:
    """把 LangGraph 输出 + 回调 Trace + 节点 Trace 合成统一契约结果。"""
    for k in ("llm_calls", "tool_calls", "retriever_calls", "tokens_est", "errors", "node_events"):
        ctx.metrics[k] = ctx.metrics.get(k, 0) + cb.metrics.get(k, 0)

    answer = str(out.get("answer") or "")
    if hitl:
        answer = answer or hitl.get("prompt", "流程已挂起，等待人工审批。")
    state = {
        "thread_id": thread_id,
        "mode": ctx.mode,
        "status": out.get("status"),
        "intent": out.get("intent"),
        "reason": out.get("reason"),
        "confidence": out.get("confidence"),
        "plan": out.get("plan", {}),
        "documents": out.get("documents", []),
        "citations": out.get("citations", []),
        "tool_results": out.get("tool_results", []),
        "memory_ctx": out.get("memory_ctx", []),
        "context_block": out.get("context_block", ""),
        "case_id": out.get("case_id"),
        "budget": out.get("budget", {}),
        "node_path": out.get("node_path", []),
        "graph_nodes": meta.get("graph_nodes", []),
        "callback_node_path": cb.node_path,
        "tools": meta.get("tools", []),
        "retriever": meta.get("retriever", {}),
        "errors": out.get("errors", []),
        "checkpoints": [],
        "components": {
            "ChatModel": "langchain_ollama.ChatOllama" if ctx.mode == "ollama" else "TeachingChatModel(BaseChatModel)",
            "Embeddings": "OllamaEmbeddings" if ctx.mode == "ollama" else "TeachingEmbeddings(Embeddings)",
            "Tools": "langchain_core.tools.@tool → bind_tools → ToolNode",
            "Retriever": "langchain_core.retrievers.BaseRetriever（三路 RRF 融合）",
            "VectorStore": "langchain_core.vectorstores.InMemoryVectorStore",
            "Graph": "langgraph.graph.StateGraph + checkpointer=MemorySaver",
            "HITL": "langgraph.types.interrupt + Command(resume=...)",
            "Memory": "langgraph.store.memory.InMemoryStore + checkpointer",
            "StructuredOutput": "langchain_core.output_parsers.PydanticOutputParser",
            "Context": "langchain_core.messages.trim_messages",
            "Trace": "langchain_core.callbacks.BaseCallbackHandler",
            "MCP": "langchain-mcp-adapters.MultiServerMCPClient → ch10 stdio MCP Server",
        },
    }
    if out.get("case_id"):
        from common import hr_data
        state["checkpoints"] = hr_data.load_checkpoints(out["case_id"])
    return ctx.result(answer, state=state, hitl=hitl)


def _hitl_from(interrupt_value: dict, thread_id: str, out: dict) -> dict:
    return {
        "required": True,
        "thread_id": thread_id,
        # 前端审批按钮回传 hitl.case_id，必须等于 thread_id 才能命中
        # MemorySaver 里 interrupt 的 checkpoint；业务单号另放 hr_case_id。
        "case_id": thread_id,
        "hr_case_id": interrupt_value.get("case_id") or out.get("case_id"),
        "prompt": interrupt_value.get("prompt", "等待人工审批"),
        "actions": interrupt_value.get("actions", [{"key": "approve", "label": "通过"}]),
        "sop": interrupt_value.get("sop", ""),
        "resume_endpoint": "/api/fullchain/resume",
        "note": "LangGraph interrupt 挂起；调用 POST /api/fullchain/resume 并带 thread_id + action 即可从断点续跑",
    }


def run(payload: dict | None = None, ctx: Context | None = None) -> dict:
    payload = payload or {}
    ctx = ctx or Context("ch16")
    if not LC_AVAILABLE:
        return ctx.result(
            "本章需要 LangChain 生态依赖，当前环境未安装。请在工程根目录执行："
            "pip install -r requirements-langchain.txt",
            state={"missing_dependency": LC_IMPORT_ERROR,
                   "note": "前 15 章仍可正常运行，不受影响"},
        )

    scenario = str(payload.get("scenario", "leave"))
    if scenario == "eval":
        return _run_eval(payload, ctx)

    question = str(payload.get("question") or SCENARIOS.get(scenario, SCENARIOS["leave"]))
    if scenario == "mcp":
        payload = dict(payload, use_mcp=True)
    p = _params(payload)
    thread_id = str(payload.get("thread_id") or "lc-" + uuid.uuid4().hex[:10])

    # 带 action 的调用视为人工审批恢复
    if payload.get("action") and payload.get("thread_id"):
        return resume(payload, ctx)

    cb = TraceCallbackHandler()
    graph, meta = build_graph(ctx=ctx, mode=ctx.mode, **p)
    cfg = config_for(thread_id, cb, p["max_steps"])
    ctx.trace("state", f"LangGraph 全链路启动｜scenario={scenario}｜thread_id={thread_id}",
              graph_nodes=meta["graph_nodes"], components=meta["tools"])

    out = graph.invoke({
        "messages": [HumanMessage(content=question)],
        "question": question, "thread_id": thread_id,
        "emp_id": p["emp_id"], "mode": ctx.mode,
    }, config=cfg)

    iv = pending_interrupt(graph, cfg)
    hitl = _hitl_from(iv, thread_id, out) if iv else None
    if hitl:
        ctx.trace("hitl", f"LangGraph interrupt 挂起：{hitl['prompt']}", thread_id=thread_id)
    else:
        ctx.trace("state", "全链路闭环：compose → write_memory → END")
    result = _assemble(ctx, cb, out, meta, thread_id, hitl)
    result["steps"] = _merge_steps(ctx, cb)
    return result


def _merge_steps(ctx: Context, cb: TraceCallbackHandler) -> list[dict]:
    from dataclasses import asdict
    steps = [asdict(s) for s in ctx.steps] + [dict(s) for s in cb.steps]
    steps.sort(key=lambda s: s.get("ts", ""))
    return steps


def resume(payload: dict | None = None, ctx: Context | None = None) -> dict:
    payload = payload or {}
    ctx = ctx or Context("ch16")
    if not LC_AVAILABLE:
        return ctx.result("缺少 LangChain 依赖：pip install -r requirements-langchain.txt",
                          state={"missing_dependency": LC_IMPORT_ERROR})
    thread_id = str(payload.get("thread_id") or "")
    action = str(payload.get("action", "approve"))
    approver = str(payload.get("approver", "李四（主管）"))
    if not thread_id:
        return ctx.result("恢复失败：缺少 thread_id", state={"error": "thread_id required"})
    p = _params(payload)
    cb = TraceCallbackHandler()
    graph, meta = build_graph(ctx=ctx, mode=ctx.mode, **p)
    cfg = config_for(thread_id, cb, p["max_steps"])
    ctx.trace("hitl", f"用 Command(resume={{action:{action}}}) 从 LangGraph checkpoint 恢复",
              thread_id=thread_id, action=action, approver=approver)
    try:
        out = graph.invoke(Command(resume={"action": action, "approver": approver}), config=cfg)
    except Exception as exc:
        ctx.trace("error", f"恢复失败：{exc}")
        return ctx.result(f"恢复失败：{exc}", state={"thread_id": thread_id,
                                                   "hint": "thread_id 不存在或该流程已完成"})
    iv = pending_interrupt(graph, cfg)
    hitl = _hitl_from(iv, thread_id, out) if iv else None
    ctx.trace("state", f"恢复完成，流程状态 → {out.get('status')}")
    result = _assemble(ctx, cb, out, meta, thread_id, hitl)
    result["steps"] = _merge_steps(ctx, cb)
    return result


def state(thread_id: str) -> dict:
    """查看某个 thread 的 checkpoint（教学用，生产走持久化 checkpointer）。"""
    if not LC_AVAILABLE:
        return {"error": LC_IMPORT_ERROR}
    from langgraph.graph import StateGraph  # noqa: F401
    graph, meta = build_graph(ctx=Context("ch16"), mode="mock")
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        snap = graph.get_state(cfg)
        # checkpointer 快照里可能混入函数 / 回调对象；统一转成可 JSON 序列化结构
        raw = {k: v for k, v in snap.values.items() if k != "messages"}
        safe = json.loads(json.dumps(raw, default=str, ensure_ascii=False))
        count = getattr(snap, "count", None)   # 某些版本是方法而非属性，不能进 JSON
        return {"thread_id": thread_id, "next": list(snap.next), "values": safe,
                "interrupts": [str(getattr(i, "value", ""))[:200]
                               for t in (snap.tasks or []) for i in (getattr(t, "interrupts", ()) or ())],
                "checkpoint_count": count if isinstance(count, int) else None}
    except Exception as exc:
        return {"error": str(exc), "thread_id": thread_id}


def _run_eval(payload: dict, ctx: Context) -> dict:
    """端到端 Golden Case 回归：一次跑通 5 条不同意图的全链路。"""
    if not LC_AVAILABLE:
        return ctx.result("缺少 LangChain 依赖，无法跑回归集",
                          state={"missing_dependency": LC_IMPORT_ERROR})
    results = []
    total_tokens = 0
    for name, (exp_intent, keyword, label) in EXPECT.items():
        q = SCENARIOS[name]
        sub = Context("ch16_eval")
        r = run({"scenario": name, "question": q, "thread_id": "eval-" + uuid.uuid4().hex[:8]}, sub)
        total_tokens += r.get("metrics", {}).get("tokens_est", 0)
        st = r.get("state", {})
        intent_ok = st.get("intent") == exp_intent
        kw_ok = keyword in str(r.get("answer", ""))
        # onboarding 走到 interrupt 挂起，证据是生成的 case_id（状态机副作用）
        tool_or_rag = bool(st.get("tool_results") or st.get("documents") or st.get("case_id"))
        passed = intent_ok and kw_ok and tool_or_rag
        results.append({"case": name, "label": label, "question": q,
                        "expect_intent": exp_intent, "actual_intent": st.get("intent"),
                        "intent_ok": intent_ok, "keyword": keyword, "keyword_ok": kw_ok,
                        "has_evidence": tool_or_rag, "passed": passed,
                        "answer_preview": str(r.get("answer", ""))[:120],
                        "nodes": st.get("callback_node_path", []),
                        "latency_ms": r.get("metrics", {}).get("duration_ms", 0)})
    total = len(results)
    passed_n = sum(r["passed"] for r in results)
    lat = sorted(r["latency_ms"] for r in results)
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
    summary = {
        "任务成功率": f"{passed_n}/{total}",
        "意图路由准确率": f"{sum(r['intent_ok'] for r in results)}/{total}",
        "证据命中率": f"{sum(r['has_evidence'] for r in results)}/{total}",
        "P95 端到端延迟(ms)": p95,
        "Token 成本(估算)": total_tokens,
        "覆盖节点": sorted({n for r in results for n in r["nodes"]}),
    }
    ctx.trace("state", f"端到端回归完成：任务成功率 {passed_n}/{total}")
    return ctx.result(
        f"LangGraph 全链路端到端回归：{passed_n}/{total} 通过，覆盖工具 / RAG / Text2SQL / 图谱 / 状态机+HITL 五条路径。",
        state={"eval_summary": summary, "cases": results,
               "note": "onboarding 用例会停在 interrupt 人工节点，属于预期行为（Agent 不自动代批）"},
    )


if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
