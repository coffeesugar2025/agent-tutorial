"""LangChain 检索层：一个真正的 BaseRetriever，融合「全文 + 向量 + 图谱」三路。

对应第 7–9 章，但这次用 LangChain 的标准接口承载：
  - InMemoryVectorStore（langchain_core）+ Embeddings  ← 向量路
  - common.bm25.BM25Index                            ← 全文路
  - common.graph.SimpleGraph                          ← 图谱路（多跳子图）
  - RRF 倒数排名融合 → list[Document]，metadata 带版本与引用编号

版本治理与第 8 章联动：优先读 kb_chunks 表里 active=1 的片段，
所以你在 ch08 点过「发布 V2.4 / 撤销」，这里检索到的制度版本会跟着变。
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import InMemoryVectorStore
from pydantic import ConfigDict, Field

from . import hr_data
from .bm25 import BM25Index
from .graph import SimpleGraph
from .lc_models import build_embeddings
from .vectorstore import rrf_fuse


def _slice(text: str, size: int = 260, overlap: int = 40) -> list[dict]:
    version = (re.search(r"版本\s*(V[\d.]+)", text) or [None, "V1.0"])[1]
    parts = re.split(r"(?m)^##\s+", text)
    out: list[dict] = []
    seq = 0
    for part in parts[1:] or [text]:
        lines = part.strip().splitlines()
        section = lines[0].strip() if lines else "正文"
        body = "\n".join(lines[1:]).strip()
        start = 0
        while start < len(body):
            piece = body[start:start + size]
            if len(piece.strip()) < 20:
                break
            seq += 1
            out.append({"chunk_id": f"chunk::{version}::{seq}", "doc_id": "handbook",
                        "title": "HR 制度合集", "version": version, "section": section,
                        "seq": seq, "text": piece.strip(), "active": True})
            start += size - overlap
    return out


def load_active_chunks() -> list[dict]:
    """优先用第 8 章的知识库表（带版本/active 治理），没有就退回原始文档。"""
    conn = hr_data.connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM kb_chunks WHERE active=1")]
    finally:
        conn.close()
    if rows:
        return [{"chunk_id": r["chunk_id"], "doc_id": r["doc_id"],
                 "title": r["doc_id"], "version": r["version"],
                 "section": f"片段 {r['seq']}", "seq": r["seq"],
                 "text": r["text"], "active": True} for r in rows]
    chunks: list[dict] = []
    for d in hr_data.load_handbook():
        for c in _slice(d["text"]):
            c["doc_id"] = d["doc_id"]
            c["title"] = d["title"]
            c["chunk_id"] = f"{d['doc_id']}::{c['chunk_id']}"
            chunks.append(c)
    return chunks


class HRHybridRetriever(BaseRetriever):
    """三路混合检索器：实现 LangChain BaseRetriever._get_relevant_documents。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vector_store: Any = Field(default=None, exclude=True)
    bm25: Any = Field(default=None, exclude=True)
    graph: Any = Field(default=None, exclude=True)
    embeddings: Any = Field(default=None, exclude=True)
    chunk_meta: dict[str, dict] = Field(default_factory=dict)
    top_k: int = 3

    def _get_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Document]:
        # ① 向量路（LangChain VectorStore 标准接口）
        try:
            pairs = self.vector_store.similarity_search_with_score(query, k=5)
            vec_hits = [{"id": d.metadata["chunk_id"], "text": d.page_content,
                         "score": float(score), "source": "vector"} for d, score in pairs]
        except Exception:
            docs = self.vector_store.similarity_search(query, k=5)
            vec_hits = [{"id": d.metadata["chunk_id"], "text": d.page_content,
                         "score": 0.0, "source": "vector"} for d in docs]

        # ② 全文路（BM25，擅长条款号 / 编号 / 人名）
        bm_hits = self.bm25.search(query, top_k=5)

        # ③ 图谱路（关系型问题：多跳子图作为证据）
        graph_hits: list[dict] = []
        entity = next((n for n in ("张三", "李四", "王五", "赵六", "孙七", "周总") if n in query), None)
        if entity and any(w in query for w in ("项目", "汇报", "同事", "关系", "图谱", "技能")):
            sub, triples = self.graph.subgraph_text(entity, hops=2)
            if triples:
                graph_hits.append({"id": f"graph::{entity}", "text": sub,
                                   "score": 0.9, "source": "graph"})

        # ④ RRF 融合（按名次，无需手调三路权重）
        fused = rrf_fuse([vec_hits, bm_hits, graph_hits], k=60, top_k=self.top_k)

        out: list[Document] = []
        for i, hit in enumerate(fused, start=1):
            meta = dict(self.chunk_meta.get(hit["id"], {}))
            meta.update({"chunk_id": hit["id"], "citation_id": i,
                         "sources": hit.get("sources", []), "rrf": round(hit.get("rrf", 0), 5)})
            out.append(Document(page_content=hit.get("text", ""), metadata=meta))
        return out


def build_retriever(mode: str = "mock", top_k: int = 3) -> tuple[HRHybridRetriever, dict]:
    chunks = load_active_chunks()
    emb = build_embeddings(mode)
    vs = InMemoryVectorStore(emb)
    bm = BM25Index()
    meta: dict[str, dict] = {}
    docs = []
    for c in chunks:
        m = {k: c[k] for k in ("doc_id", "title", "version", "section", "seq", "active")}
        m["chunk_id"] = c["chunk_id"]
        meta[c["chunk_id"]] = m
        bm.add(c["chunk_id"], c["text"], m)
        docs.append(Document(page_content=c["text"], metadata=m))
    if docs:
        vs.add_documents(docs)
    retriever = HRHybridRetriever(
        vector_store=vs, bm25=bm, graph=SimpleGraph(hr_data.ORG_EDGES),
        embeddings=emb, chunk_meta=meta, top_k=top_k,
    )
    versions = sorted({c["version"] for c in chunks})
    return retriever, {"chunk_count": len(chunks), "versions": versions,
                       "retriever_class": "langchain_core.retrievers.BaseRetriever",
                       "vector_store": "langchain_core.vectorstores.InMemoryVectorStore",
                       "embeddings": type(emb).__name__,
                       "fusion": "RRF(vector + bm25 + graph)"}
