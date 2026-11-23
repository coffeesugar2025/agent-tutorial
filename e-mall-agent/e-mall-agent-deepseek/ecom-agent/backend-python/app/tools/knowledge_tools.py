"""知识库检索工具（混合检索 → 引用）。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.common.envelope import CamelModel
from app.tools.base import Risk, ToolContext, ToolSpec


class SearchKnowledgeArgs(CamelModel):
    query: str = Field(min_length=1, max_length=200, description="检索问题")
    top_k: int = Field(default=3, ge=1, le=8, description="返回条数")
    doc_types: list[str] | None = Field(
        default=None, description="文档类型过滤：POLICY/MANUAL/FAQ/PRODUCT_DOC"
    )
    mode: str = Field(default="hybrid", description="检索模式：hybrid/dense/sparse")


async def search_knowledge(
    ctx: ToolContext,
    query: str,
    top_k: int = 3,
    doc_types: list[str] | None = None,
    mode: str = "hybrid",
) -> dict[str, Any]:
    """检索知识库，返回带 docId/chunkId 的引用列表（runtime 据此发 citation 事件）。"""
    from app.rag.retriever import hybrid_search

    result = await hybrid_search(
        query=query,
        top_k=top_k,
        doc_types=doc_types,
        mode=mode,
        visibility="PUBLIC",
        recorder=ctx.recorder,
    )
    items = [
        {
            "documentId": item.document_id,
            "chunkId": item.chunk_id,
            "title": item.title,
            "content": item.content,
            "snippet": item.snippet,
            "score": item.score,
            "denseScore": item.dense_score,
            "sparseScore": item.sparse_score,
            "rerankScore": item.rerank_score,
            "route": item.route,
        }
        for item in result.items
    ]
    citations = [
        {
            "docId": item.document_id,
            "chunkId": item.chunk_id,
            "title": item.title,
            "snippet": item.snippet,
            "score": item.score,
        }
        for item in result.items
    ]
    return {
        "query": query,
        "items": items,
        "citations": citations,
        "hit": bool(items),
        "debug": result.debug,
        "message": "" if items else "知识库未检索到相关内容",
    }


SEARCH_KNOWLEDGE = ToolSpec(
    name="search_knowledge",
    description="检索平台知识库（退款政策、售后流程、商品文档、FAQ），返回可引用的原文片段。",
    func=search_knowledge,
    risk=Risk.READ,
    args_model=SearchKnowledgeArgs,
    timeout_seconds=15,
    max_retries=1,
    summarize=lambda data: (
        f"命中 {len(data.get('items', []))} 条知识片段"
        if data.get("hit")
        else "知识库未命中"
    ),
)

__all__ = ["SEARCH_KNOWLEDGE", "search_knowledge"]
