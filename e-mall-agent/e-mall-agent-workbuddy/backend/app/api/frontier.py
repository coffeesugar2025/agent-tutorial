"""前沿能力端点：安全防御、反思/编排/A2A、Tool RAG、模型工程、
查询改写/高级 RAG/ACL/抽取、限流熔断/灰度/密钥/合规、评测四件套。

本路由把上一轮补齐的能力模块以 REST 形式暴露，与 capabilities.py 并列，
避免单个路由文件过度膨胀。所有端点都走 require(...) 权限校验。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..agents.tool_retriever import ToolRetriever
from ..a2a.delegate import LocalTaskDelegator
from ..a2a.models import AgentCard, AgentCapabilities, AgentSkill
from ..a2a.registry import AgentCardRegistry
from ..domain.models import User
from ..eval.attribution import FeedbackLoop
from ..eval.experiment import Experiment, ExperimentReport, significance_test
from ..eval.judge import JudgeConfig, LLMJudgeScorer, default_judge, judge_consistency
from ..eval.trajectory import TrajectoryScorer, with_trajectory
from ..llm.benchmark import ModelProfile, ModelRequirements, select_model
from ..llm.reasoning import ReasoningConfig, build_reasoning_model_kwargs, is_reasoning_model
from ..llm.structured import extract_json, validate_structured
from ..llm.tokenizer import EnhancedTokenCounter
from ..observability.alerting import AlertManager, HealthProbe
from ..orchestration.factory import ALL_PATTERNS, build_pattern
from ..prompts.registry import PromptRegistry
from ..rag.acl import ACLFilteredRetriever
from ..rag.advanced import AgenticRAG, CorrectiveRAG, SelfRAG
from ..rag.extraction import extract_knowledge
from ..rag.query import (HyDEGenerator, MultiQueryGenerator, QueryDecomposer,
                         StepBackRewriter)
from ..rag.ragas_metrics import evaluate_rag
from ..reflection.loop import ReflexionLoop
from ..reliability.flags import FeatureFlag
from ..reliability.secrets import SecretRing
from ..security.injection import InjectionScanner, isolate_untrusted, least_privilege_system_prompt
from ..security.moderation import check_output, detect_jailbreak
from ..security.tool_guard import ToolGuard
from .routes import require
from .schemas import (
    ACLRetrieveRequest, A2ADelegateRequest, AdvancedRAGRequest, AttributionRequest,
    ExtractionRequest, FeatureFlagRequest, GuardRequest, JudgeRequest,
    ModelSelectRequest, OrchestrationRequest, PromptRenderRequest,
    PromptRequest, PromptTemplateRequest, QueryRewriteRequest, RagasRequest,
    ReasoningRequest, StructuredRequest, TokenizeRequest, ToolGuardRequest,
    ToolRetrieveRequest, TrajectoryRequest, ExperimentRequest, HealthCheckRequest,
)

router = APIRouter(prefix="/api/frontier")


def _dump(obj: Any) -> Any:
    """统一序列化 dataclass / pydantic / 普通对象。"""
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (list, tuple)):
        return [_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


# ============ 单例 ============
_prompt_registry: PromptRegistry | None = None
_injection_scanner: InjectionScanner | None = None
_token_counter: EnhancedTokenCounter | None = None
_a2a_registry: AgentCardRegistry | None = None
_a2a_delegator: LocalTaskDelegator | None = None
_health_probe: HealthProbe | None = None


def get_prompt_registry() -> PromptRegistry:
    global _prompt_registry
    if _prompt_registry is None:
        _prompt_registry = PromptRegistry()
        _prompt_registry.init_from_personas()
    return _prompt_registry


def get_injection_scanner() -> InjectionScanner:
    global _injection_scanner
    if _injection_scanner is None:
        _injection_scanner = InjectionScanner()
    return _injection_scanner


def get_token_counter() -> EnhancedTokenCounter:
    global _token_counter
    if _token_counter is None:
        _token_counter = EnhancedTokenCounter()
    return _token_counter


def get_a2a() -> tuple[AgentCardRegistry, LocalTaskDelegator]:
    global _a2a_registry, _a2a_delegator
    if _a2a_registry is None or _a2a_delegator is None:
        _a2a_registry = AgentCardRegistry()
        for name, skills in {
            "product-agent": ["商品检索", "商品推荐"],
            "order-agent": ["订单查询", "下单"],
            "refund-agent": ["售后退款"],
        }.items():
            _a2a_registry.register(AgentCard(
                name=name, version="1.0.0",
                description=f"{name} 的能力卡片",
                capabilities=AgentCapabilities(),
                skills=[AgentSkill(id=s, name=s, description=s) for s in skills],
                endpoint=f"local://{name}",
            ))
        _a2a_delegator = LocalTaskDelegator(registry=_a2a_registry)
        for name in ("product-agent", "order-agent", "refund-agent"):
            _a2a_delegator.register_handler(
                name, lambda task, n=name: f"[{n}] 已处理: {task}")
    return _a2a_registry, _a2a_delegator


# ============ 1. 安全防御 ============
@router.post("/security/scan")
async def security_scan(payload: GuardRequest,
                        user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """Prompt 注入 + 越狱联合扫描，返回风险等级与命中规则。"""
    injection = get_injection_scanner().scan(payload.text)
    jailbreak = detect_jailbreak(payload.text)
    output = check_output(payload.text)
    untrusted = None
    if payload.untrusted:
        isolated = isolate_untrusted(payload.untrusted, scanner=get_injection_scanner())
        untrusted = {
            "isolated_text": str(isolated),
            "suspicious": bool(get_injection_scanner().scan(payload.untrusted).suspicious),
        }
    system_prompt = least_privilege_system_prompt(
        role=payload.role, allowed_tools=payload.allowed_tools)
    return {
        "injection": injection.as_dict(),
        "jailbreak": jailbreak.as_dict(),
        "output": output.as_dict(),
        "untrusted": untrusted,
        "system_prompt": system_prompt,
    }


@router.post("/security/tools")
async def security_tools(payload: ToolGuardRequest,
                         user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """工具清单投毒检测 + 白名单强制过滤。"""
    from ..security.tool_guard import ToolSpec

    guard = ToolGuard(whitelist=payload.whitelist) if payload.whitelist else ToolGuard()
    report = guard.validate_manifest(payload.tools) if payload.tools else None
    allowed = guard.enforce_tools(payload.tools, actor=user.id) if payload.tools else []
    return {
        "validation": report.as_dict() if report else None,
        "allowed_count": len(allowed),
        "allowed": [ToolSpec.from_obj(t).name for t in allowed],
    }


# ============ 2. Agent 工程 ============
@router.post("/reflection")
async def reflection_run(payload: PromptRequest,
                         user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """反思自纠错循环（executor/critic 为本地可注入 stub）。"""
    def executor(task: str, feedback: str | None) -> str:
        prefix = f"修订({feedback[:30]}) " if feedback else ""
        return f"{prefix}答案: {task}"

    def critic(task: str, answer: str) -> Any:
        from ..reflection.models import Critique
        score = 0.6 if not answer.startswith("修订") else 0.95
        return Critique(score=score, feedback="需要补充细节" if score < 0.8 else "已达标",
                        accepted=score >= 0.8)

    loop = ReflexionLoop(executor, critic, max_iterations=payload.max_iterations,
                         score_threshold=payload.score_threshold)
    return _dump(loop.run(payload.task))


@router.post("/orchestration")
async def orchestration_run(payload: OrchestrationRequest,
                            user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """LangGraph 官方编排模式执行（parallel/orchestrator-workers 等）。"""
    from ..orchestration.factory import (EVALUATOR_OPTIMIZER, ORCHESTRATOR_WORKERS,
                                         PARALLELIZATION, PROMPT_CHAINING, ROUTING)

    if payload.pattern not in ALL_PATTERNS:
        raise HTTPException(status_code=400,
                            detail=f"pattern 必须是 {', '.join(ALL_PATTERNS)} 之一")
    names = payload.workers or ["worker-a", "worker-b"]
    # 本地确定性 worker：把任务加工成带标签的结果，便于演示各模式拓扑。
    def worker(label: str):
        return lambda task: f"[{label}] {task}"

    workers_fn = {n: worker(n) for n in names}
    kwargs: dict[str, Any]
    if payload.pattern in (PARALLELIZATION, PROMPT_CHAINING):
        kwargs = {"workers": list(workers_fn.values())}
    elif payload.pattern == ORCHESTRATOR_WORKERS:
        kwargs = {"workers": workers_fn}
    elif payload.pattern == ROUTING:
        kwargs = {"routes": workers_fn, "classifier": lambda t: names[0]}
    else:  # EVALUATOR_OPTIMIZER
        kwargs = {
            "generator": lambda task, feedback: f"{task}{('+' + feedback) if feedback else ''}",
            "evaluator": lambda task, draft: (0.95, "达标"),
        }
    try:
        graph = build_pattern(payload.pattern, **kwargs)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await graph.ainvoke({"task": payload.task, "user": user.id})
    return _dump(result)


@router.get("/a2a/cards")
async def a2a_cards(user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """列出已注册的 Agent Card（A2A 协议骨架）。"""
    registry, _ = get_a2a()
    return {"count": len(registry.list()), "cards": _dump(registry.list())}


@router.post("/a2a/delegate")
async def a2a_delegate(payload: A2ADelegateRequest,
                       user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """本地任务委派：SUBMITTED → WORKING → COMPLETED/FAILED。"""
    _, delegator = get_a2a()
    try:
        task = await delegator.asubmit(payload.agent, payload.task)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _dump(task)


@router.post("/tools/retrieve")
async def tools_retrieve(payload: ToolRetrieveRequest,
                         user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """Tool RAG：按语义检索最相关的工具，可叠加 RBAC 过滤。"""
    from ..agents.tools import local_tools

    retriever = ToolRetriever(local_tools())
    if payload.use_rbac:
        tools = retriever.filtered_search(payload.query, user, top_k=payload.top_k)
        names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
        return {"count": len(names), "tools": names}
    hits = retriever.search_with_scores(payload.query, top_k=payload.top_k)
    return {
        "count": len(hits),
        "tools": [{"name": h.name, "score": round(h.score, 4)} for h in hits],
    }


# ============ 3. 模型工程 ============
@router.post("/llm/reasoning")
async def llm_reasoning(payload: ReasoningRequest,
                        user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """推理模型参数生成：o1/R1 用 reasoning_effort，普通模型用 temperature。"""
    cfg = ReasoningConfig(reasoning_effort=payload.effort)
    if payload.max_cot_tokens is not None:
        cfg.max_cot_tokens = payload.max_cot_tokens
    return {
        "is_reasoning_model": is_reasoning_model(payload.model),
        "model_kwargs": build_reasoning_model_kwargs(payload.model, cfg),
        "config": _dump(cfg),
    }


@router.post("/llm/tokenize")
async def llm_tokenize(payload: TokenizeRequest,
                       user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """精确 Token 计数与预算切分（可选 tiktoken，缺省回退估算）。"""
    counter = get_token_counter()
    counts = [counter.count(t) for t in payload.texts]
    split = counter.budget_split(payload.texts, payload.limit)
    return {"counts": counts, "total": sum(counts), "budget_split": _dump(split)}


@router.post("/llm/structured")
async def llm_structured(payload: StructuredRequest,
                         user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """结构化输出：从文本提取 JSON 并做 Schema 校验。"""
    extracted = extract_json(payload.text)
    from pydantic import BaseModel

    class Answer(BaseModel):
        answer: str

    validated = validate_structured(payload.text, Answer)
    return {"extracted": extracted, "validated": _dump(validated)}


@router.post("/llm/select-model")
async def llm_select_model(payload: ModelSelectRequest,
                           user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """模型选型：质量/成本/延迟三维加权决策。"""
    profiles = [ModelProfile(**p) for p in payload.profiles]
    req = ModelRequirements(**payload.requirements)
    return _dump(select_model(profiles, req))


# ============ 4. Prompt 版本管理 ============
@router.post("/prompts/register")
async def prompt_register(payload: PromptTemplateRequest,
                          user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """注册版本化 Prompt 模板。"""
    registry = get_prompt_registry()
    item = registry.register(payload.name, payload.version, payload.template)
    if payload.set_active:
        registry.set_active(payload.name, payload.version)
    return _dump(item)


@router.post("/prompts/render")
async def prompt_render(payload: PromptRenderRequest,
                        user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """按版本渲染 Prompt 模板。"""
    registry = get_prompt_registry()
    try:
        rendered = registry.render(payload.name, payload.version, **payload.variables)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"rendered": rendered, "versions": registry.list_versions(payload.name)}


# ============ 5. RAG 进阶 ============
@router.post("/rag/rewrite")
async def rag_rewrite(payload: QueryRewriteRequest,
                      user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """查询改写：Multi-Query / HyDE / Step-back / 分解。"""
    mode = payload.mode
    if mode == "multi":
        result: Any = MultiQueryGenerator().generate(payload.query)
    elif mode == "hyde":
        result = HyDEGenerator().generate(payload.query)
    elif mode == "stepback":
        result = StepBackRewriter().rewrite(payload.query)
    elif mode == "decompose":
        result = QueryDecomposer().decompose(payload.query)
    else:
        raise HTTPException(status_code=400,
                            detail="mode 必须是 multi/hyde/stepback/decompose")
    return {"mode": mode, "query": payload.query, "result": _dump(result)}


@router.post("/rag/ragas")
async def rag_ragas(payload: RagasRequest,
                    user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """RAGAS 四项指标：Faithfulness / Relevancy / Precision / Recall。"""
    return evaluate_rag(payload.question, payload.answer,
                        payload.contexts, payload.ground_truth).as_dict()


@router.post("/rag/advanced")
async def rag_advanced(payload: AdvancedRAGRequest,
                       user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """高级 RAG 范式：Corrective / Self-RAG / Agentic。"""
    modes = {"corrective": CorrectiveRAG, "self_rag": SelfRAG, "agentic": AgenticRAG}
    if payload.mode not in modes:
        raise HTTPException(status_code=400,
                            detail="mode 必须是 corrective/self_rag/agentic")
    return _dump(modes[payload.mode]().run(payload.question))


@router.post("/rag/acl")
async def rag_acl(payload: ACLRetrieveRequest,
                  user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """权限感知检索：按 user_id 强制行级过滤。"""
    from .capabilities import get_hybrid_retriever

    base = get_hybrid_retriever()
    retriever = ACLFilteredRetriever(base.search, deny_by_default=False)
    results = retriever.retrieve(payload.query, payload.user_id,
                                 tenant=payload.tenant)
    return {"count": len(results), "results": _dump(results)}


@router.post("/rag/extract")
async def rag_extract(payload: ExtractionRequest,
                      user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """知识抽取流水线：实体 / 关系 / 事件三阶段。"""
    return _dump(extract_knowledge(payload.text))


# ============ 6. 可靠性 ============
@router.post("/reliability/flags")
async def reliability_flags(payload: FeatureFlagRequest,
                            user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """Feature Flag：按 user_id 哈希分桶的灰度/A-B 分流。"""
    flag = FeatureFlag(name=payload.name, enabled=payload.enabled,
                       rollout=payload.ratio, variants=payload.variants)
    return {
        "enabled": flag.is_enabled(payload.user_id),
        "variant": flag.variant(payload.user_id),
        "bucket": flag.bucket(payload.user_id),
    }


@router.post("/reliability/health")
async def reliability_health(payload: HealthCheckRequest,
                             user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """按 SLO/告警规则评估指标快照，产出告警。"""
    manager = AlertManager()
    return {"alerts": _dump(manager.evaluate(payload.snapshot))}


@router.get("/reliability/probes")
async def reliability_probes(user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """依赖探活注册表状态。"""
    global _health_probe
    if _health_probe is None:
        _health_probe = HealthProbe()
    return {"checks": list(_health_probe.names()) if hasattr(_health_probe, "names") else []}


# ============ 7. 评测四件套 ============
@router.post("/eval/judge")
async def eval_judge(payload: JudgeRequest,
                     user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """LLM-as-Judge 打分 + 与人工评分的一致性。"""
    scorer = LLMJudgeScorer(JudgeConfig(rubric=payload.rubric, judge=default_judge))
    score = scorer(payload.answer, payload.expected)
    result: dict[str, Any] = {"score": round(score, 4)}
    if payload.human_score is not None:
        agree = judge_consistency([score], [payload.human_score])
        result["consistency"] = _dump(agree)
    return result


@router.post("/eval/trajectory")
async def eval_trajectory(payload: TrajectoryRequest,
                          user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """轨迹评测：工具调用序列 LCS 相似度。"""
    scorer = TrajectoryScorer()
    return _dump(scorer.score(payload.trace, payload.expected))


@router.post("/eval/attribution")
async def eval_attribution(payload: AttributionRequest,
                           user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """错误归因 + bad case 标注闭环。"""
    from ..eval.dataset import GoldenCase

    case = GoldenCase.from_dict(payload.case)
    loop = FeedbackLoop()
    bad = loop.submit_bad_case(case, payload.result, payload.trace)
    response: dict[str, Any] = {"bad_case": _dump(bad)}
    if payload.promote:
        bad = loop.annotate(bad.id, note="API 自动标注")
        golden = loop.promote_to_golden(bad.id)
        response["promoted"] = _dump(golden)
    return response


@router.post("/eval/experiment")
async def eval_experiment(payload: ExperimentRequest,
                          user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """A-B 实验：稳定分桶 + Welch t 检验显著性。"""
    exp = Experiment(name=payload.name, treatment_ratio=payload.treatment_ratio)
    group = exp.assign(payload.user_id)
    test = significance_test(payload.control_scores, payload.treatment_scores)
    report = ExperimentReport(experiment=payload.name, metric="quality", test=test)
    return {"assigned_group": group, "report": _dump(report)}
