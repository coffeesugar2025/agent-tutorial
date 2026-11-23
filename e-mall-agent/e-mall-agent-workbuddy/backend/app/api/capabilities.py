"""扩展能力端点：规划、混合检索、记忆、沙箱、评测与指标。

这些端点把 app/planning、app/memory、app/rag、app/sandbox、app/eval、
app/observability 的能力以 REST 形式暴露，供前端或外部系统调用。
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..domain.models import User
from ..eval import CaseDataset, EvalReport, Evaluator, GoldenCase, RegressionGate
from ..memory import InMemoryMemoryStore, MemoryManager
from ..observability.metrics import MetricsCollector
from ..planning import create_planning_graph
from ..rag.citation import CitationValidator, GroundednessScorer
from ..rag.graphrag import GraphRAGRetriever
from ..rag.hybrid import HybridRetriever
from ..rag.pipeline import SEED_DOCS
from ..rag.text2sql import Text2Cypher, Text2SQL, create_demo_db
from ..sandbox import CodeModeRunner, CodeSandbox
from .routes import require
from .schemas import (
    CitationRequest,
    EvalRequest,
    GraphRAGRequest,
    HybridSearchRequest,
    MemoryWriteRequest,
    PlanRequest,
    SandboxRequest,
    Text2SQLRequest,
)

router = APIRouter(prefix="/api/capabilities")


# ---------- singletons ----------
_memory: MemoryManager | None = None
_metrics: MetricsCollector | None = None
_text2sql: Text2SQL | None = None
_graphrag: GraphRAGRetriever | None = None


def get_memory_manager() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager(InMemoryMemoryStore())
    return _memory


def get_metrics() -> MetricsCollector:
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def get_text2sql() -> Text2SQL:
    global _text2sql
    if _text2sql is None:
        _text2sql = Text2SQL(create_demo_db())
    return _text2sql


def get_graphrag() -> GraphRAGRetriever:
    global _graphrag
    if _graphrag is None:
        _graphrag = GraphRAGRetriever()
        _graphrag.build([
            {"content": doc["content"],
             "metadata": {"source": doc.get("source", ""),
                          "category": doc.get("category", "general")}}
            for doc in SEED_DOCS
        ])
    return _graphrag


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    """懒加载混合检索器，种子知识来自 pipeline 的同一批文档。"""
    return HybridRetriever([
        {"id": f"seed-{i}", "content": d["content"],
         "metadata": {"source": d.get("source", "知识库"),
                      "category": d.get("category", "general")}}
        for i, d in enumerate(SEED_DOCS)
    ])


# ---------- planning ----------
@router.post("/plan")
async def plan(payload: PlanRequest,
               user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """ReAct 或 Plan-and-Solve 执行目标，返回答案与完整轨迹。"""
    try:
        graph = create_planning_graph(mode=payload.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await graph.ainvoke({"goal": payload.goal, "user": user.model_dump()})
    return {
        "answer": result.get("answer", ""),
        "trace": result.get("trace", []),
        "terminated_reason": result.get("terminated_reason", ""),
        "mode": payload.mode,
    }


# ---------- hybrid rag ----------
@router.post("/rag/hybrid")
async def hybrid_search(payload: HybridSearchRequest,
                        user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """BM25 + 向量 RRF 混合检索，返回来源明细与可注入上下文。"""
    retriever = get_hybrid_retriever()
    weights = None
    if payload.mode == "bm25":
        weights = (0.0, 1.0)
    elif payload.mode == "vector":
        weights = (1.0, 0.0)
    elif payload.mode != "hybrid":
        raise HTTPException(status_code=400, detail="mode 必须是 hybrid / bm25 / vector")
    chunks = retriever.search(payload.query, top_k=payload.top_k, weights=weights)
    return {
        "count": len(chunks),
        "results": [
            {
                "id": c.id,
                "content": c.content,
                "score": c.score,
                "rank": c.rank,
                "metadata": c.metadata,
                "sources": {
                    k: {"channel": v.channel, "rank": v.rank,
                        "raw_score": v.raw_score, "contribution": v.contribution}
                    for k, v in c.sources.items()
                },
            }
            for c in chunks
        ],
        "context": "\n".join(c.content for c in chunks),
    }


# ---------- memory ----------
@router.get("/memory")
async def memory_recall(thread_id: str = "default", query: str = "",
                        user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """召回当前用户的三层记忆（严格按 user_id 隔离）。"""
    result = get_memory_manager().recall(user.id, thread_id, query)
    return result.as_dict()


@router.post("/memory")
async def memory_write(payload: MemoryWriteRequest,
                       user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """写入会话/情景记忆，可选写入用户偏好或事实。"""
    manager = get_memory_manager()
    episode = manager.remember(
        user.id, payload.thread_id, payload.user_input, payload.assistant_output,
        goal=payload.user_input or None,
    )
    stored: dict[str, Any] = {"episode": episode.as_dict() if episode else None}
    if payload.preference:
        name = str(payload.preference.get("name", ""))
        value = payload.preference.get("value")
        if name:
            manager.user.upsert_preference(
                user.id, name, value,
                confidence=float(payload.preference.get("confidence", 1.0)),
            )
            stored["preference"] = name
    if payload.fact:
        content = str(payload.fact.get("content", ""))
        if content:
            manager.user.add_fact(
                user.id, content,
                source=str(payload.fact.get("source", "user")),
            )
            stored["fact"] = content
    return stored


@router.delete("/memory/{target_user_id}")
async def memory_forget(target_user_id: str,
                        user: User = Depends(require("audit:read"))) -> dict[str, Any]:
    """合规删除指定用户的全部记忆（仅管理员）。"""
    return get_memory_manager().forget_user(target_user_id)


# ---------- sandbox ----------
@router.post("/sandbox")
async def sandbox_run(payload: SandboxRequest,
                      user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """在受限沙箱中执行代码，可选 Code Mode 工具编排。"""
    if payload.mode == "plain":
        result = await asyncio.to_thread(CodeSandbox().run, payload.code)
    elif payload.mode == "code_mode":
        from ..agents.tools import local_tools
        from ..security.rbac import filter_tools

        tools = filter_tools(local_tools(), user)
        runner = CodeModeRunner()
        result = await asyncio.to_thread(runner.run, payload.code, None, tools)
    else:
        raise HTTPException(status_code=400, detail="mode 必须是 plain / code_mode")
    return result.as_dict()


# ---------- advanced RAG ----------
@router.post("/rag/text2sql")
async def text2sql(payload: Text2SQLRequest,
                   user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """自然语言转受限 SELECT（禁止 DML、自动 LIMIT）并在 SQLite 执行。"""
    engine = get_text2sql()
    try:
        result = engine.run(payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sql": result.sql, "params": list(result.params),
            "columns": result.columns, "rows": result.as_dicts()}


@router.get("/rag/text2cypher")
async def text2cypher(question: str = "查一下订单O1001的商品",
                      user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """自然语言转 Cypher 查询（模板 + 参数），供 Neo4j 直接执行。"""
    query = Text2Cypher().generate(question)
    return {"cypher": query.cypher, "params": query.params, "pattern": query.pattern}


@router.post("/rag/graph")
async def graphrag(payload: GraphRAGRequest,
                   user: User = Depends(require("product:read"))) -> dict[str, Any]:
    """知识图谱 1-2 跳子图检索，返回可注入 prompt 的自然语言描述。"""
    context = get_graphrag().retrieve(payload.query, hops=payload.hops)
    return {
        "entity_id": context.entity_id,
        "description": context.description,
        "entities": [e.model_dump() if hasattr(e, "model_dump") else vars(e)
                     for e in context.entities],
        "relations": [r.model_dump() if hasattr(r, "model_dump") else vars(r)
                      for r in context.relations],
    }


@router.post("/rag/citation")
async def citation_check(payload: CitationRequest,
                         user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """引用标记校验 + groundedness 评分，用于幻觉控制。"""
    validator = CitationValidator(payload.chunks)
    citation_report = validator.validate(payload.answer)
    grounded = GroundednessScorer(payload.chunks).score(payload.answer)
    return {
        "citation": citation_report.model_dump() if hasattr(citation_report, "model_dump")
                    else vars(citation_report),
        "groundedness": grounded.model_dump() if hasattr(grounded, "model_dump")
                        else vars(grounded),
    }


# ---------- metrics & eval ----------
@router.get("/metrics")
async def metrics_snapshot(user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """指标快照：成功率、工具错误率、Token 总量、延迟 P50/P95/P99。"""
    return get_metrics().snapshot()


@router.post("/eval")
async def evaluate(payload: EvalRequest,
                   user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """运行 Golden Case 批量评测，可附基线通过率做回归门禁判断。"""
    dataset = CaseDataset([GoldenCase.from_dict(c) for c in payload.cases])

    def runner(case: GoldenCase) -> dict[str, Any]:
        if payload.runner == "agent":
            return {"answer": str(case.input), "route": "general"}
        return {"answer": str(case.input)}

    report = await Evaluator().evaluate(dataset, runner)
    response: dict[str, Any] = {"report": report.as_dict()}
    if payload.baseline_pass_rate is not None:
        baseline = EvalReport(
            total=report.total, passed=round(payload.baseline_pass_rate * report.total),
            pass_rate=payload.baseline_pass_rate,
        )
        response["gate"] = RegressionGate().check(baseline, report).as_dict()
    return response
