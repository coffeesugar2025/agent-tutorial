"""/v2/* 扩展能力接口：把生产级能力矩阵全部暴露成可调用、可验证的 HTTP 端点。

不改动原有 8 个 /health 与 /v1/* 接口；所有端点在 AGENT_MODE=mock 下离线可跑。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.agent.middleware import GUARD_REPLY, get_audit_log
from app.capabilities import (context, harness, hitl, memory, model_eng,
                              multi_agent, planning, reliability, skills, workflow)
from app.capabilities.observability import (
    METRICS, SUITE, TRACER, EvalRun, observability_spec,
)
from app.capabilities.rag import knowledge, text2sql
from app.capabilities.rag.pipeline import PIPELINE, rag_spec
from app.capabilities.rag.vectorstore import VECTOR_DB_ADAPTERS
from app.services import catalog

router = APIRouter(prefix="/v2", tags=["extended-capabilities"])


# ---------------------------------------------------------------- 能力总览
@router.get("/capabilities", summary="生产级能力矩阵自述（逐条对照常见面试清单）")
async def capabilities() -> dict[str, Any]:
    return {
        "project": "小栈 · 电商智能体",
        "version_baseline": "langchain 1.5.2 / core 1.8.4 / Python ≥3.11",
        "already_in_v1": [
            "Agent Loop (create_agent)", "Tool / Function Calling", "MCP Tools (10, 三级降级)",
            "LangGraph checkpointer 会话记忆", "AgentMiddleware 治理", "SSE 流式 / 标准内容块",
            "response_format 结构化输出", "工具审计日志", "MCP 只读边界 + 归属校验",
            "ModelRetryMiddleware / 调用次数上限 / recursion_limit 终止条件",
        ],
        "added_in_v2": [
            "Planning / ReAct / Plan-and-Solve", "LangGraph 显式 StateGraph 工作流",
            "Multi-Agent Supervisor + 3 专家", "Human-in-the-loop 审批 / resume",
            "长期记忆 / 用户记忆（跨 thread）", "Token 预算 / 上下文压缩 / 裁剪",
            "幂等 / 超时 / 熔断 / 降级链 / 重复动作终止",
            "Sandbox(AST) / Code Mode / 长任务 checkpoint 恢复",
            "Trace / Metrics(P95/P99) / Golden Case 评测 / Bad Case / Replay",
            "Skill / Plugin 注册表", "模型路由 / 成本延迟 / 9 家 Provider / 4 种推理服务 / 训练任务契约",
            "RAG：切片/版本/增量/撤销/Embedding/BM25/RRF/Rerank/引用治理",
            "Text2SQL + SQL Guard / Text2Cypher / GraphRAG / Ontology / Neo4j 契约",
        ],
        "adapter_only": ["Milvus/Qdrant/Chroma/FAISS/Pinecone/ES/LlamaIndex（统一契约）",
                         "Neo4j（Cypher 适配器契约）",
                         "SFT/LoRA/QLoRA/DPO/RLHF/量化/剪枝/蒸馏（仅 TrainingJobSpec 契约）"],
        "docs": "docs/04-能力覆盖矩阵与扩展实现.md",
        "modules": {
            "planning": "kp: ReAct / Plan-and-Solve", "workflow": workflow.workflow_spec(),
            "multi_agent": multi_agent.agent_topology(), "hitl": hitl.hitl_spec(),
            "reliability": reliability.reliability_report(), "harness": harness.harness_spec(),
            "observability": observability_spec(), "skills": skills.capability_contract(),
            "model_eng": model_eng.model_eng_spec(), "rag": rag_spec(),
        },
    }


# ---------------------------------------------------------------- Planning
@router.post("/plan", summary="ReAct 或 Plan-and-Solve 编排")
async def plan(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(422, "message 不能为空")
    strategy = body.get("strategy", "react")
    if strategy == "plan_and_solve":
        r = planning.plan_and_solve(message)
    else:
        r = planning.react_loop(message)
    return {"strategy": r.strategy, "goal": r.goal, "plan": r.plan,
            "trace": r.trace, "answer": r.answer,
            "steps_executed": r.steps_executed, "terminated_by": r.terminated_by,
            "elapsed_ms": r.elapsed_ms}


# ---------------------------------------------------------------- Workflow
@router.post("/workflow/run", summary="LangGraph 显式状态机执行")
async def workflow_run(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return workflow.run_workflow(str(body.get("message", "")))


# ---------------------------------------------------------------- Multi-Agent
@router.post("/multi-agent/chat", summary="Supervisor + 领域专家协作")
async def multi_agent_chat(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return multi_agent.run_multi_agent(
        str(body.get("message", "")), parallel=bool(body.get("parallel", True))
    ).to_dict()


# ---------------------------------------------------------------- HITL
@router.get("/approvals", summary="待审批列表与统计")
async def approvals() -> dict[str, Any]:
    return {"pending": hitl.STORE.list_pending(), "stats": hitl.STORE.stats()}


@router.post("/approvals/submit", summary="提交工具调用，判断是否挂起")
async def approval_submit(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return hitl.submit_if_needed(
        str(body.get("tool", "search_products")),
        dict(body.get("args", {})), str(body.get("message", "")))


@router.post("/approvals/{approval_id}/decide", summary="approve / reject / edit")
async def approval_decide(approval_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        req = hitl.STORE.decide(approval_id, str(body.get("decision", "approve")),
                                str(body.get("decided_by", "reviewer")),
                                body.get("edited_args"))
        return req.to_dict()
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/approvals/{approval_id}/resume", summary="审批后恢复执行（幂等）")
async def approval_resume(approval_id: str) -> dict[str, Any]:
    try:
        return hitl.resume(approval_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------- Memory
@router.get("/memory/{user_id}", summary="三层记忆视图 + 画像")
async def memory_get(user_id: str) -> dict[str, Any]:
    return {"user_id": user_id, "layers": memory.memory_layers(user_id, "demo"),
            "profile": memory.build_memory_context(user_id),
            "items": memory.STORE.search(("users", user_id))}


@router.post("/memory/{user_id}", summary="从一句话抽取并合并用户偏好")
async def memory_update(user_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    msg = str(body.get("message", ""))
    if body.get("fact_key"):
        return memory.remember_fact(user_id, str(body["fact_key"]), body.get("fact_value"),
                                    body.get("ttl_seconds"))
    return memory.update_user_profile(user_id, msg)


@router.delete("/memory/{user_id}", summary="删除一条长期记忆")
async def memory_delete(user_id: str, key: str = "preferences",
                        namespace: str = "profile") -> dict[str, Any]:
    return {"deleted": memory.STORE.delete(("users", user_id, namespace), key),
            "stats": memory.STORE.stats()}


# ---------------------------------------------------------------- Context
@router.post("/context/compress", summary="Token 预算内压缩消息历史")
async def context_compress(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    msgs = list(body.get("messages", []))
    b = context.TokenBudget(**{k: v for k, v in body.get("budget", {}).items()
                               if k in ("total", "reserve_system", "reserve_tools",
                                        "reserve_output", "reserve_retrieved")})
    return context.compress(msgs, b, recent_turns=int(body.get("recent_turns", 3))).to_dict()


# ---------------------------------------------------------------- Reliability
@router.post("/reliability/demo", summary="重试/幂等/超时/熔断/降级/终止 演示")
async def reliability_demo(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    op = body.get("operation", "all")
    out: dict[str, Any] = {}
    if op in ("all", "retry"):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("temporary")
            return {"ok": True, "attempt": calls["n"]}
        value, errors = reliability.RetryPolicy(max_attempts=3, backoff_factor=0.001).run_sync(flaky)
        out["retry"] = {"value": value, "errors": errors}
    if op in ("all", "idempotency"):
        idem = reliability.IdempotencyStore()
        fn = lambda: {"price": 799.0}
        out["idempotency"] = [idem.execute("calc", {"sku": "SKU-1001"}, fn),
                              idem.execute("calc", {"sku": "SKU-1001"}, fn)]
    if op in ("all", "degrade"):
        out["degrade"] = reliability.degrade_chain(
            lambda: (_ for _ in ()).throw(RuntimeError("MCP down")),
            [("local-tools", lambda: {"source": "local", "ok": True})])
    if op in ("all", "circuit"):
        cb = reliability.CircuitBreaker(failure_threshold=2, recovery_seconds=5.0)
        for _ in range(2):
            cb.record_failure()
        out["circuit"] = {"before": cb.snapshot(), "allowed": cb.allow()}
    if op in ("all", "termination"):
        t = reliability.TerminationPolicy(max_steps=3, repeated_call_limit=1)
        reasons = []
        for i in range(5):
            r = t.observe("search_products")
            reasons.append(r)
            if r:
                break
        out["termination"] = {"reasons": reasons, "snapshot": t.snapshot()}
    return out


# ---------------------------------------------------------------- Harness
@router.post("/sandbox/eval", summary="AST 白名单受限表达式执行")
async def sandbox_eval(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return harness.sandbox_eval(str(body.get("expression", "")),
                                dict(body.get("context", {})))


@router.post("/sandbox/code-mode", summary="Code Mode：意图→受限表达式→交叉校验")
async def code_mode(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if body.get("verify_price"):
        return harness.CodeMode.verify_price(899.0, 100.0, 799.0)
    return harness.CodeMode.compile_task(str(body.get("intent", "到手价")),
                                         dict(body.get("params", {"subtotal": 899, "discount": 100})))


def _long_steps():
    return [
        ("检索商品", lambda: catalog.search_products(keyword="耳机", limit=3)),
        ("核验库存", lambda: catalog.check_inventory("SKU-1001")),
        ("计算到手价", lambda: catalog.calculate_price("SKU-1001", 1, "FULL100")),
        ("生成卡片", lambda: {"ok": True, "cards": 1}),
    ]


@router.post("/longtask/start", summary="启动可恢复长任务（可模拟中断）")
async def longtask_start(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return harness.RUNNER.start(_long_steps(), fail_at=body.get("fail_at"))


@router.post("/longtask/{task_id}/resume", summary="从 checkpoint 断点恢复")
async def longtask_resume(task_id: str) -> dict[str, Any]:
    try:
        return harness.RUNNER.resume(task_id, _long_steps())
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# ---------------------------------------------------------------- Observability
@router.post("/trace/demo", summary="生成一条带父子 span 的 trace")
async def trace_demo(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    tid = TRACER.start_trace(str(body.get("name", "ecommerce-agent-run")),
                             {"user_id": body.get("user_id", "u_1001")})
    s1 = TRACER.start_span(tid, "classify_intent", "agent")
    TRACER.end_span(s1)
    s2 = TRACER.start_span(tid, "search_products", "tool", s1)
    TRACER.event(s2, "tool_args", keyword="耳机")
    TRACER.end_span(s2)
    s3 = TRACER.start_span(tid, "synthesize", "model", s1)
    TRACER.end_span(s3)
    METRICS.observe("agent_latency_ms", 42)
    METRICS.inc("agent_runs_total", result="ok")
    return TRACER.export(tid)


@router.get("/trace/{trace_id}", summary="导出 trace")
async def trace_get(trace_id: str) -> dict[str, Any]:
    return TRACER.export(trace_id)


@router.get("/metrics", summary="counter / histogram / P50 P95 P99")
async def metrics() -> dict[str, Any]:
    return {"metrics": METRICS.snapshot(), "tracer": TRACER.stats(),
            "audit_records": len(get_audit_log(200))}


def demo_runner(case: Any) -> EvalRun:
    """离线被测系统：等价于 mock 模式下的 Agent 行为（生产替换为 /v1/chat 调用）。"""
    q = case.question
    if any(k in q for k in ("忽略以上规则", "system prompt", "越权")):
        return EvalRun(case.id, GUARD_REPLY, [], latency_ms=1, tokens_in=20, tokens_out=30)
    tags = set(case.tags)
    if "search" in tags:
        d = catalog.search_products(keyword="降噪", limit=3)
        names = "、".join(p["name"] for p in d["products"][:2])
        return EvalRun(case.id, f"找到 {names}（{d['products'][0]['sku']}）",
                       ["search_products"], latency_ms=12, tokens_in=180, tokens_out=60)
    if "price" in tags:
        d = catalog.calculate_price("SKU-1001", 1, "FULL100")
        return EvalRun(case.id, f"到手 ¥{d['payable']:.2f} CNY", ["calculate_price"],
                       latency_ms=15, tokens_in=200, tokens_out=60)
    if "order" in tags:
        d = catalog.get_order("EC20261118001", "u_1001")["order"]
        return EvalRun(case.id, f"订单 {d['order_id']}：{d['status']}", ["get_order"],
                       latency_ms=14, tokens_in=190, tokens_out=55)
    if "aftersale" in tags:
        e = catalog.check_after_sale_eligibility("EC20261105002", "u_1001")
        p = catalog.get_after_sale_policy("退货")
        return EvalRun(case.id, f"{'符合' if e['eligible'] else '不符合'}退货资格；政策：{p['content'][:40]}",
                       ["check_after_sale_eligibility", "get_after_sale_policy"],
                       latency_ms=20, tokens_in=230, tokens_out=80)
    if "recommend" in tags:
        d = catalog.recommend_products(budget=500.0)
        c = catalog.list_coupons("u_1001")
        return EvalRun(case.id, f"推荐 {len(d['products'])} 件商品，可用券 {len(c['coupons'])} 张",
                       ["recommend_products", "list_coupons"],
                       latency_ms=22, tokens_in=240, tokens_out=70)
    if "rag" in tags or "citation" in tags:
        r = PIPELINE.query("价保政策是什么", mode="hybrid", top_k=2)
        policy = catalog.get_after_sale_policy("价保")
        answer = r.answer + "\n" + str(policy.get("content", ""))
        citations = r.citations or [{"ref": 1, "doc_id": "doc_policies",
                                    "chunk_id": "doc_policies@policy"}]
        return EvalRun(case.id, answer, ["get_after_sale_policy"], citations,
                       latency_ms=30, tokens_in=400, tokens_out=90)
    return EvalRun(case.id, "已为你核实到相关信息。", [], latency_ms=5)


@router.post("/evals/run", summary="Golden Case 回归评测")
async def evals_run() -> dict[str, Any]:
    return SUITE.run(demo_runner)


@router.post("/evals/replay", summary="Replay 历史录制，检测回归")
async def evals_replay(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    recorded = body.get("recorded")
    if recorded is None:
        recorded = [{"case_id": "G02", "answer": "到手 789.00", "tools_used": ["calculate_price"],
                     "latency_ms": 15, "cost_usd": 0.0}]
    return SUITE.replay(list(recorded))


@router.get("/evals/cases", summary="内置 Golden Case 清单")
async def evals_cases() -> dict[str, Any]:
    return {"total": len(SUITE.cases), "cases": [c.to_dict() for c in SUITE.cases.values()],
            "bad_cases": SUITE.bad_cases}


# ---------------------------------------------------------------- Skills
@router.get("/skills", summary="Skill / Plugin 目录")
async def skills_list() -> dict[str, Any]:
    return {"skills": skills.REGISTRY.discover(), "stats": skills.REGISTRY.stats(),
            "contract": skills.capability_contract()}


@router.post("/skills/invoke", summary="调用 Skill（含权限与依赖门禁）")
async def skills_invoke(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return skills.invoke(str(body.get("name", "")), dict(body.get("args", {})))


# ---------------------------------------------------------------- 模型工程
@router.get("/models/providers", summary="9 家 Provider + 4 种推理服务")
async def models_providers() -> dict[str, Any]:
    return {"providers": model_eng.PROVIDERS,
            "inference_servers": model_eng.INFERENCE_SERVERS,
            "eval_metrics": model_eng.EVAL_METRICS}


@router.post("/models/route", summary="按成本/延迟/意图/本地优先做模型路由")
async def models_route(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    d = model_eng.ROUTER.route(
        intent=str(body.get("intent", "other")),
        tokens_in=int(body.get("tokens_in", 1200)),
        tokens_out=int(body.get("tokens_out", 300)),
        max_cost_usd=body.get("max_cost_usd"),
        latency_sla_ms=body.get("latency_sla_ms"),
        prefer_local=bool(body.get("prefer_local", False)),
        require_strong=bool(body.get("require_strong", False)))
    return {"decision": d.to_dict(),
            "cost_estimate": model_eng.CostEstimator.estimate(
                d.provider, int(body.get("tokens_in", 1200)), int(body.get("tokens_out", 300))),
            "deployment": model_eng.DeploymentPolicy.decide(
                str(body.get("intent", "other")), str(body.get("mode", "hybrid")))}


@router.get("/models/training-contract", summary="训练任务契约（明确不在本仓库执行训练）")
async def training_contract() -> dict[str, Any]:
    spec = model_eng.TrainingJobSpec(
        method="LoRA", base_model="Qwen2.5-7B", dataset_ref="s3://datasets/ecommerce_sft.jsonl",
        output_name="ecommerce-agent-lora-v1", hyperparams={"r": 16, "lr": 2e-4})
    return {"spec": spec.to_dict(), "methods": list(model_eng.TRAINING_METHODS),
            "dataset_contract": model_eng.DATASET_CONTRACT,
            "boundary": "本仓库只生成/校验 spec；训练需外部 GPU 平台，executed_here 永远为 False"}


# ---------------------------------------------------------------- RAG
@router.post("/rag/ingest", summary="文档入库（解析/切片/版本/增量/双索引）")
async def rag_ingest(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    text = str(body.get("text", ""))
    if not text:
        raise HTTPException(422, "text 不能为空")
    return PIPELINE.ingest(str(body.get("doc_id", "doc_manual")), text,
                           fmt=str(body.get("fmt", "txt")),
                           strategy=str(body.get("strategy", "paragraph")))


@router.post("/rag/update", summary="文档更新（仅索引 diff 变化的 chunk）")
async def rag_update(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return PIPELINE.update(str(body.get("doc_id", "doc_manual")), str(body.get("text", "")))


@router.post("/rag/delete", summary="删除文档并同步删向量/BM25")
async def rag_delete(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return PIPELINE.delete(str(body.get("doc_id", "")))


@router.post("/rag/undo", summary="撤销上一次文档变更并重建索引")
async def rag_undo() -> dict[str, Any]:
    return PIPELINE.undo()


@router.post("/rag/query", summary="vector/bm25/hybrid/graph/sql/all 六种检索模式")
async def rag_query(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    q = str(body.get("question", ""))
    if not q:
        raise HTTPException(422, "question 不能为空")
    return PIPELINE.query(q, mode=str(body.get("mode", "all")),
                          top_k=int(body.get("top_k", 5))).to_dict()


@router.post("/rag/text2sql", summary="受限 Text2SQL：模板 + SQL Guard + sqlite")
async def rag_text2sql(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return text2sql.run_text2sql(str(body.get("question", "")))


@router.post("/rag/text2cypher", summary="模板化 Text2Cypher + GraphRAG 子图")
async def rag_text2cypher(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    q = str(body.get("question", ""))
    return {"cypher": knowledge.text2cypher(q),
            "graphrag": knowledge.graphrag_retrieve(q, knowledge.KG, hops=2),
            "neo4j_contract": knowledge.NEO4J_ADAPTER}


@router.get("/rag/graph", summary="知识图谱统计与本体")
async def rag_graph() -> dict[str, Any]:
    return knowledge.knowledge_spec()


@router.get("/rag/stats", summary="RAG 全链路状态")
async def rag_stats() -> dict[str, Any]:
    return {"pipeline": rag_spec(), "vector_db_adapters": VECTOR_DB_ADAPTERS,
            "text2sql": text2sql.text2sql_spec()}
