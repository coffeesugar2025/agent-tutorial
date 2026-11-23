"""混合检索：dense + sparse → RRF 融合 → rerank → 父子块展开。

降级路径（Milvus 不可用 / 集合为空）：
1. 内存向量库（同进程内索引过的文档仍然可检索）；
2. 关键词候选 + BM25-lite 重排（跨进程、跨重启依然有效，最多 500 条候选）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.common.tokens import estimate_tokens
from app.config import settings
from app.infra.db import session_scope
from app.infra.milvus import MilvusUnavailable
from app.infra.models import KnowledgeChunk, KnowledgeDocument
from app.obs.metrics import record_degradation, record_rag_query
from app.obs.trace import SPAN_RETRIEVAL
from app.rag.embedding import get_embedding
from app.rag.rerank import get_reranker
from app.rag.sparse import sparse_vector
from app.rag.store import Hit, get_store, keyword_search_chunks

logger = logging.getLogger(__name__)

RRF_K = 60


@dataclass
class RetrievedChunk:
    """检索结果项。"""

    chunk_id: int
    document_id: int
    title: str
    content: str
    score: float = 0.0
    snippet: str = ""
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    route: str = "dense+sparse"
    parent_content: str = ""
    doc_type: str = ""
    visibility: str = "PUBLIC"

    def __post_init__(self) -> None:
        if not self.snippet:
            text = self.content or ""
            self.snippet = text[:180] + ("…" if len(text) > 180 else "")


@dataclass
class RetrievalResult:
    """检索结果 + 调试信息。"""

    items: list[RetrievedChunk] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def hit(self) -> bool:
        return bool(self.items)


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """RRF：``score(d) = Σ 1/(k + rank_i(d))``。"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def rrf_fuse(dense: list[Hit], sparse: list[Hit], k: int = RRF_K) -> list[tuple[Hit, float]]:
    """融合两路召回，返回 ``[(hit, rrf_score)]``（降序）。"""
    by_id: dict[int, Hit] = {}
    for hit in dense:
        by_id[hit.id] = hit
    for hit in sparse:
        by_id.setdefault(hit.id, hit)
    scores = reciprocal_rank_fusion(
        [[hit.id for hit in dense], [hit.id for hit in sparse]], k=k
    )
    fused: list[tuple[Hit, float]] = []
    for doc_id, score in scores.items():
        hit = by_id.get(doc_id)
        if hit is not None:
            fused.append((hit, round(score, 8)))
    fused.sort(key=lambda item: item[1], reverse=True)
    return fused


def _load_chunk_meta(chunk_ids: list[int]) -> dict[int, dict[str, Any]]:
    """补齐标题/父块/类型（内存命中或调试场景 payload 可能不全）。"""
    if not chunk_ids:
        return {}
    try:
        with session_scope() as db:
            rows = (
                db.query(
                    KnowledgeChunk.id,
                    KnowledgeChunk.parent_content,
                    KnowledgeChunk.document_id,
                    KnowledgeDocument.title,
                    KnowledgeDocument.doc_type,
                    KnowledgeDocument.visibility,
                )
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .filter(KnowledgeChunk.id.in_(chunk_ids))
                .all()
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载 chunk 元信息失败: %s", exc)
        return {}
    return {
        int(row[0]): {
            "parent_content": row[1] or "",
            "document_id": int(row[2]),
            "title": row[3],
            "doc_type": row[4],
            "visibility": row[5],
        }
        for row in rows
    }


def _to_chunk(
    hit: Hit,
    score: float,
    route: str,
    dense_score: float | None,
    sparse_score: float | None,
    meta: dict[int, dict[str, Any]],
) -> RetrievedChunk:
    payload = hit.payload or {}
    chunk_id = int(payload.get("chunk_id") or hit.id)
    extra = meta.get(chunk_id, {})
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=int(payload.get("document_id") or extra.get("document_id") or 0),
        title=str(payload.get("title") or extra.get("title") or "未命名文档"),
        content=hit.content,
        score=round(float(score), 6),
        dense_score=dense_score,
        sparse_score=sparse_score,
        route=route,
        parent_content=str(payload.get("parent_content") or extra.get("parent_content") or hit.content),
        doc_type=str(payload.get("doc_type") or extra.get("doc_type") or ""),
        visibility=str(payload.get("visibility") or extra.get("visibility") or "PUBLIC"),
    )


async def hybrid_search(
    query: str,
    top_k: int | None = None,
    doc_types: list[str] | None = None,
    mode: str = "hybrid",
    visibility: str | None = "PUBLIC",
    recorder: Any = None,
) -> RetrievalResult:
    """混合检索主入口（异步：向量库/embedding 均为阻塞 IO，放入线程池）。"""
    started = time.perf_counter()
    top_k = top_k or settings.knowledge_top_k
    mode = (mode or "hybrid").lower()
    degraded = False
    collection = settings.collection("knowledge")
    filters: dict[str, Any] = {}
    if visibility:
        filters["visibility"] = visibility
    if doc_types:
        filters["doc_type"] = [doc.upper() for doc in doc_types]

    dense_hits: list[Hit] = []
    sparse_hits: list[Hit] = []
    store_name = "memory"
    store = get_store()
    store_name = store.name

    if mode in {"hybrid", "dense"}:
        try:
            embedding = get_embedding()
            query_vector = await asyncio.to_thread(embedding.embed_query, query)
            await asyncio.to_thread(store.ensure, collection, len(query_vector))
            dense_hits = await asyncio.to_thread(
                store.search_dense, collection, query_vector, settings.retrieval_dense_top_k, filters
            )
        except (MilvusUnavailable, Exception) as exc:  # noqa: BLE001
            degraded = True
            record_degradation("retrieval", f"dense_failed:{type(exc).__name__}")
            logger.warning("dense 检索失败，降级关键词: %s", exc)

    if mode in {"hybrid", "sparse"}:
        try:
            query_sparse = await asyncio.to_thread(sparse_vector, query)
            sparse_hits = await asyncio.to_thread(
                store.search_sparse, collection, query_sparse, settings.retrieval_sparse_top_k, filters
            )
        except Exception as exc:  # noqa: BLE001
            degraded = True
            record_degradation("retrieval", f"sparse_failed:{type(exc).__name__}")
            logger.warning("sparse 检索失败: %s", exc)

    candidates: list[RetrievedChunk] = []
    if dense_hits or sparse_hits:
        fused = rrf_fuse(dense_hits, sparse_hits) if mode == "hybrid" else [
            (hit, hit.score) for hit in (dense_hits or sparse_hits)
        ]
        dense_scores = {hit.id: hit.score for hit in dense_hits}
        sparse_scores = {hit.id: hit.score for hit in sparse_hits}
        chunk_ids = [int((hit.payload or {}).get("chunk_id") or hit.id) for hit, _ in fused]
        meta = await asyncio.to_thread(_load_chunk_meta, chunk_ids)
        for hit, score in fused:
            chunk_id = int((hit.payload or {}).get("chunk_id") or hit.id)
            candidates.append(
                _to_chunk(
                    hit,
                    score,
                    route="dense+sparse" if hit.id in dense_scores and hit.id in sparse_scores
                    else ("dense" if hit.id in dense_scores else "sparse"),
                    dense_score=dense_scores.get(hit.id),
                    sparse_score=sparse_scores.get(hit.id),
                    meta=meta,
                )
            )

    if not candidates:
        degraded = True
        record_degradation("retrieval", "empty_vector_hits_use_keyword")
        keyword_hits = await asyncio.to_thread(
            keyword_search_chunks, query, settings.retrieval_sparse_top_k, doc_types, visibility
        )
        chunk_ids = [int((hit.payload or {}).get("chunk_id") or hit.id) for hit in keyword_hits]
        meta = await asyncio.to_thread(_load_chunk_meta, chunk_ids)
        candidates = [
            _to_chunk(hit, hit.score, route="keyword", dense_score=None, sparse_score=None, meta=meta)
            for hit in keyword_hits
        ]

    # rerank（只对头部候选，控制成本）
    rerank_applied = False
    if candidates:
        reranker = get_reranker()
        rerank_applied = reranker.name != "none"
        try:
            candidates = await reranker.rerank(
                query, candidates, top_n=max(top_k, settings.rerank_top_n)
            )
        except Exception as exc:  # noqa: BLE001
            record_degradation("rerank", f"failed:{type(exc).__name__}")
            logger.warning("重排异常，保持原顺序: %s", exc)

    # 父子块去重：同一父块只保留最高分的子块
    deduped: list[RetrievedChunk] = []
    seen_parents: set[str] = set()
    for item in candidates:
        key = f"{item.document_id}:{hash(item.parent_content)}"
        if key in seen_parents:
            continue
        seen_parents.add(key)
        deduped.append(item)
        if len(deduped) >= top_k:
            break

    latency_ms = int((time.perf_counter() - started) * 1000)
    record_rag_query(mode, latency_ms / 1000)
    if recorder is not None:
        recorder.record_span(
            name="retrieval.knowledge",
            span_type=SPAN_RETRIEVAL,
            inputs={"query": query, "topK": top_k, "mode": mode, "docTypes": doc_types},
            output={"hits": len(deduped), "degraded": degraded, "store": store_name},
            latency_ms=latency_ms,
        )
    debug = {
        "denseTopK": len(dense_hits),
        "sparseTopK": len(sparse_hits),
        "rerankTopN": len(deduped),
        "latencyMs": latency_ms,
        "mode": mode,
        "store": store_name,
        "degraded": degraded,
        "rerankApplied": rerank_applied,
        "contextTokens": sum(estimate_tokens(item.content) for item in deduped),
    }
    return RetrievalResult(items=deduped, debug=debug)


async def search_knowledge_for_prompt(query: str, top_k: int = 3, recorder: Any = None) -> RetrievalResult:
    """便捷封装：给 agent 预取知识（system prompt 里注入"参考依据"）。"""
    try:
        return await hybrid_search(query, top_k=top_k, recorder=recorder)
    except Exception as exc:  # noqa: BLE001
        logger.warning("预取知识失败: %s", exc)
        return RetrievalResult(items=[], debug={"error": str(exc)})


__all__ = [
    "RRF_K",
    "RetrievalResult",
    "RetrievedChunk",
    "hybrid_search",
    "reciprocal_rank_fusion",
    "rrf_fuse",
    "search_knowledge_for_prompt",
]
