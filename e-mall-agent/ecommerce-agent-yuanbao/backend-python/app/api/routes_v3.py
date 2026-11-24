"""/v3/* 生产加固能力接口：把总纲 P0/P1 缺口全部暴露成可调用端点。

与 /v1 /v2 并列，前端共用同一份契约；Java 后端实现同样的 /v3/* 路径。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from app.decision import decision
from app.hardening import (acl, cache, cost, errors, hitl_v2, injection, memory_v2,
                           prompt_registry, query_understanding, rag_eval, replay,
                           stability, tools)
from app.infra import adapters, llm_gateway
from app.infra.llm_gateway import GATEWAY

router = APIRouter(prefix="/v3", tags=["production-hardening"])


def _principal(x_user_id: str | None, x_tenant_id: str | None, x_roles: str | None):
    return acl.Principal.from_headers(x_user_id or "u_1001", x_tenant_id, x_roles or "user")


@router.get("/capabilities", summary="总纲 10 章知识点覆盖自述")
async def v3_capabilities() -> dict[str, Any]:
    return {
        "chapters": 10,
        "decision": "第0章 判据/L0-L4/ROI/决策树/误区自查（app/decision）",
        "model_layer": "第1章 多模型网关/路由级联/缓存布局/版本锁定（app/infra/llm_gateway）",
        "single_agent": "第2章 工具设计学/上下文/记忆治理/终止/校验",
        "orchestration": "第3章 Workflow/Multi-Agent/HITL 三粒度/MCP/沙箱/长任务/并发",
        "rag": "第4章 查询理解/ACL/混合检索/分层评估/缓存/Text2SQL/GraphRAG",
        "reliability": "第5章 错误分类/超时/幂等/熔断/ACL/Trace/Metrics/重放/发布/成本",
        "security": "第6章 间接注入数据化封装/红队集/工具副作用门禁/PII",
        "evaluation": "第7章 Golden Case/pass^k/Bad Case/Replay/三重门禁",
        "model_engineering": "第8章 训练任务契约（本仓库不执行训练）",
        "toolchain": "第9章 Prompt 仓库/CI 门禁/双后端契约/前端交互",
        "infra": adapters.infra_report(),
        "docs": "docs/03-知识点全量覆盖矩阵.md",
    }


# ---- 第 0 章
@router.post("/decision/fit", summary="任务可 Agent 化判据")
async def decision_fit(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    t = decision.TaskProfile(**{k: v for k, v in body.items()
                                if k in decision.TaskProfile.__dataclass_fields__})
    return {"fit": decision.agent_fit(t), "levels": decision.autonomy_levels(),
            "architecture": decision.architecture_tree(t),
            "forms": decision.PRODUCT_FORMS,
            "misconceptions": decision.misconception_check()}


@router.post("/decision/roi", summary="有效成本 = 单任务推理成本/成功率 + 人工兜底")
async def decision_roi(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return decision.roi(float(body.get("inference_per_task", 0.01)),
                        float(body.get("success_rate", 0.85)),
                        float(body.get("human_rate", 0.15)),
                        float(body.get("human_cost", 0.15)),
                        int(body.get("calls_per_day", 50000)))


# ---- 第 1 章 多模型
@router.get("/models", summary="多供应商能力矩阵")
async def models() -> dict[str, Any]:
    return {"providers": llm_gateway.provider_capability_matrix(),
            "inference_servers": llm_gateway.INFERENCE_SERVERS,
            "caching_layout": GATEWAY.note_caching_layout()}


@router.post("/models/chat", summary="多模型统一调用（mock 可离线）")
async def models_chat(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    r = GATEWAY.chat(str(body.get("message", "")), provider=body.get("provider"),
                     intent=str(body.get("intent", "other")),
                     system_prompt=str(body.get("system_prompt", "")),
                     reasoning_effort=body.get("reasoning_effort"),
                     cascade=bool(body.get("cascade", False)))
    cost.LEDGER.charge(r.provider, r.tokens_in, r.tokens_out,
                       llm_gateway.PROVIDERS[r.provider]["cost_in"],
                       llm_gateway.PROVIDERS[r.provider]["cost_out"])
    return {"result": r.to_dict(), "route": GATEWAY.route(
        str(body.get("intent", "other"))).__dict__}


@router.post("/models/route", summary="成本/延迟/意图/本地优先路由")
async def models_route(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    p = GATEWAY.route(str(body.get("intent", "other")),
                      max_cost_usd=body.get("max_cost_usd"),
                      latency_sla_ms=body.get("latency_sla_ms"),
                      prefer_local=bool(body.get("prefer_local", False)),
                      sensitive=bool(body.get("sensitive", False)))
    return {"plan": p.__dict__, "order": cost.optimization_order()}


# ---- 第 5/6 章 安全与可靠性
@router.post("/security/scan", summary="间接注入扫描 + 数据化封装")
async def security_scan(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    q = str(body.get("question", "退货政策"))
    passages = list(body.get("passages", []))
    return injection.build_guarded_prompt(q, passages)


@router.get("/security/redteam", summary="注入回归集（CI 必跑）")
async def security_redteam() -> dict[str, Any]:
    return injection.run_redteam()


@router.post("/errors/classify", summary="可重试错误分类")
async def errors_classify(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return errors.classify(str(body.get("message", ""))).to_dict()


@router.post("/rag/acl", summary="检索层 ACL：先过滤再检索")
async def rag_acl(body: dict[str, Any] = Body(default={}),
                  x_user_id: str | None = Header(None),
                  x_tenant_id: str | None = Header(None),
                  x_roles: str | None = Header(None)) -> dict[str, Any]:
    p = _principal(x_user_id, x_tenant_id, x_roles)
    out = acl.acl_filter(p, list(body.get("chunks", [])))
    out["milvus_expr"] = acl.acl_milvus_expr(p)
    out["no_cross_tenant"] = acl.assert_no_cross_tenant(p, out["chunks"])
    return out


# ---- 第 4 章 RAG 进阶
@router.post("/rag/understand", summary="查询改写/分解/multi-query/HyDE/不检索判定")
async def rag_understand(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return query_understanding.understand(str(body.get("question", "")),
                                          bool(body.get("has_history", False)))


@router.post("/rag/evaluate", summary="分层评估 recall@k/MRR/nDCG/context precision")
async def rag_evaluate(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return rag_eval.layered_diagnose(
        str(body.get("question", "")), set(body.get("relevant", [])),
        list(body.get("retrieved", [])), list(body.get("used_in_answer", [])),
        str(body.get("answer", "")), str(body.get("passages_text", "")),
        set(body.get("expected_facts", [])))


@router.get("/cache/report", summary="四级缓存命中率")
async def cache_report() -> dict[str, Any]:
    return {"cache": cache.CACHE.report(), "layers": ["exact", "semantic", "retrieval", "embedding"]}


@router.post("/cache/invalidate", summary="知识更新失效")
async def cache_invalidate(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return cache.CACHE.invalidate(body.get("doc_id"), bool(body.get("all", False)))


# ---- 第 5 章 可观测 / 重放 / 成本 / 发布
@router.post("/replay/record", summary="完整轨迹落盘")
async def replay_record(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    q = str(body.get("question", ""))
    steps = [("tool", "search_products", lambda: {"ok": True, "total": 3}),
             ("retrieval", "hybrid", lambda: {"hits": 2}),
             ("model", "synthesize", lambda: {"answer": "依据资料作答"})]
    t = replay.record(q, steps, str(body.get("prompt_version", "v1")))
    return t.to_dict()


@router.post("/replay/run", summary="确定性重放 / 时间旅行")
async def replay_run(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    steps = []
    return replay.deterministic_replay(str(body.get("trace_id", "")), steps,
                                       {int(k): v for k, v in (body.get("overrides") or {}).items()})


@router.post("/replay/compare", summary="改 prompt 前后轨迹 diff")
async def replay_compare(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return replay.STORE.compare(str(body.get("a", "")), str(body.get("b", "")))


@router.get("/cost/report", summary="每成功任务成本 / 有效成本 / 异常花费")
async def cost_report() -> dict[str, Any]:
    return {"report": cost.LEDGER.report(), "optimization_order": cost.optimization_order()}


@router.get("/prompts", summary="Prompt 版本 / hash / 灰度")
async def prompts() -> dict[str, Any]:
    return {"registry": prompt_registry.REGISTRY.spec(),
            "model_pin": prompt_registry.assert_model_pin(
                llm_gateway.S.model_version_pin or "deepseek-chat-2026-11-18",
                "deepseek-chat-2026-11-18")}


@router.post("/prompts/register", summary="注册新 prompt 版本（canary）")
async def prompts_register(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    v = prompt_registry.REGISTRY.register(str(body.get("prompt_id", "system.guide")),
                                          str(body.get("content", "")),
                                          traffic=float(body.get("traffic", 0.1)))
    return {"version": v.version, "hash": v.hash, "stage": v.stage}


# ---- 第 2/3/7 章
@router.get("/tools/specs", summary="工具设计学卡片（何时不该用/错误码/token 预算/幂等）")
async def tools_specs() -> dict[str, Any]:
    return {"registry": [s.name for s in tools.REGISTRY._specs.values()],
            "cards": [tools.REGISTRY.card(n) for n in
                      ["search_products", "calculate_price", "get_order",
                       "check_after_sale_eligibility", "apply_refund"]],
            "dynamic": tools.REGISTRY.dynamic_load(["订单", "价格"])}


@router.post("/memory/merge", summary="记忆写入策略 / 冲突消解 / 衰减")
async def memory_merge(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return memory_v2.MEMORY.merge(str(body.get("user_id", "u_1001")),
                                  str(body.get("message", "")))


@router.post("/hitl/submit", summary="三粒度 HITL + 自包含交接")
async def hitl_submit(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    it = hitl_v2.MANAGER.submit(str(body.get("kind", "pre_approval")),
                                str(body.get("tool", "apply_refund")),
                                dict(body.get("args", {})), str(body.get("risk", "high")),
                                str(body.get("reason", "写操作")),
                                str(body.get("trace_id", "tr_demo")),
                                float(body.get("timeout_seconds", 300)))
    return it.to_dict()


@router.post("/hitl/scan", summary="超时扫描：默认拒绝")
async def hitl_scan() -> dict[str, Any]:
    return {**hitl_v2.MANAGER.scan_timeouts(), "stats": hitl_v2.MANAGER.stats()}


@router.post("/evals/stability", summary="pass^k 稳定性（k 次全成功）")
async def evals_stability(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    from app.api.routes_ext import demo_runner
    from app.capabilities.observability import default_suite
    return stability.suite_stability(default_suite(), demo_runner,
                                     k=int(body.get("k", 3)))


@router.get("/infra", summary="四套基础设施当前生效后端")
async def infra() -> dict[str, Any]:
    return adapters.infra_report()
