"""Embedding / 向量库 / BM25 / 混合检索 / Rerank / 向量库适配器契约。

离线实现：HashEmbedding（字符 n-gram 确定性哈希 + L2 归一化）+ InMemoryVectorStore
（numpy 余弦）。生产替换为 Milvus / Qdrant / Chroma / FAISS / Pinecone / Elasticsearch
时只需实现同一个 VectorStoreAdapter 接口，Pipeline 不改。

检索链路：vector 召回 + BM25 全文召回 → RRF 融合 → Rerank 特征重排 → 返回带分数的 Hit。
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from app.capabilities.rag.chunking import Chunk


def tokenize(text: str) -> list[str]:
    """中英混排分词：英文按词，中文按单字 + 相邻双字，数字保留。"""
    text = (text or "").lower()
    toks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)
    cjk = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    bigrams = [seg[i:i + 2] for seg in cjk for i in range(len(seg) - 1)]
    return toks + bigrams


def _stable_hash(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=4).digest(), "big")


class HashEmbedding:
    """确定性离线 Embedding：无外部 API、无随机性、可复现。

    明示边界：这是用于工程链路验证的哈希特征，不是语义向量；生产替换为
    OpenAI/BGE/M3E 等真实 Embedding 时输出维度与接口保持一致即可。
    """

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for t in tokenize(text):
            vec[_stable_hash(t) % self.dim] += 1.0
            if len(t) > 1:
                vec[_stable_hash("ng:" + t) % self.dim] += 0.5
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.stack([self.embed(t) for t in texts]) if texts else np.zeros((0, self.dim))


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    version: int
    text: str
    score: float
    source: str = "vector"
    meta: dict[str, Any] = field(default_factory=dict)
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id,
                "version": self.version, "text": self.text,
                "score": round(self.score, 6), "source": self.source,
                "meta": self.meta, "rank": self.rank}


class VectorStoreAdapter(Protocol):
    """外部向量库统一契约：实现这 4 个方法即可替换内置内存实现。"""

    def upsert(self, chunks: list[Chunk]) -> int: ...
    def search(self, query: str, top_k: int = 5) -> list[Hit]: ...
    def delete(self, chunk_ids: list[str]) -> int: ...
    def stats(self) -> dict[str, Any]: ...


class InMemoryVectorStore:
    def __init__(self, embedder: HashEmbedding | None = None) -> None:
        self.embedder = embedder or HashEmbedding()
        self._items: dict[str, Chunk] = {}
        self._matrix: np.ndarray | None = None
        self._ids: list[str] = []
        self._lock = threading.RLock()

    def upsert(self, chunks: list[Chunk]) -> int:
        with self._lock:
            for c in chunks:
                self._items[c.chunk_id] = c
            self._rebuild()
            return len(chunks)

    def _rebuild(self) -> None:
        self._ids = list(self._items)
        self._matrix = (self.embedder.embed_batch([self._items[i].text for i in self._ids])
                        if self._ids else np.zeros((0, self.embedder.dim)))

    def delete(self, chunk_ids: list[str]) -> int:
        with self._lock:
            n = 0
            for cid in chunk_ids:
                if self._items.pop(cid, None) is not None:
                    n += 1
            self._rebuild()
            return n

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        with self._lock:
            if not self._ids or self._matrix is None:
                return []
            q = self.embedder.embed(query)
            sims = self._matrix @ q
            order = np.argsort(-sims)[:top_k]
            return [Hit(self._ids[i], self._items[self._ids[i]].doc_id,
                        self._items[self._ids[i]].version, self._items[self._ids[i]].text,
                        float(sims[i]), "vector", self._items[self._ids[i]].meta, r + 1)
                    for r, i in enumerate(order)]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"backend": "in-memory-numpy", "vectors": len(self._ids),
                    "dim": self.embedder.dim}


class BM25Index:
    """纯 Python BM25 全文检索（Okapi），用于与向量检索互补。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: dict[str, Chunk] = {}
        self._tf: dict[str, dict[str, int]] = {}
        self._df: dict[str, int] = {}
        self._avgdl = 1.0
        self._lock = threading.RLock()

    def upsert(self, chunks: list[Chunk]) -> int:
        with self._lock:
            for c in chunks:
                if c.chunk_id in self._docs:
                    for t in self._tf[c.chunk_id]:
                        self._df[t] = max(0, self._df.get(t, 0) - 1)
                toks = tokenize(c.text)
                self._docs[c.chunk_id] = c
                self._tf[c.chunk_id] = {}
                for t in toks:
                    self._tf[c.chunk_id][t] = self._tf[c.chunk_id].get(t, 0) + 1
                for t in self._tf[c.chunk_id]:
                    self._df[t] = self._df.get(t, 0) + 1
            lengths = [sum(v.values()) for v in self._tf.values()]
            self._avgdl = sum(lengths) / max(1, len(lengths))
            return len(chunks)

    def delete(self, chunk_ids: list[str]) -> int:
        with self._lock:
            n = 0
            for cid in chunk_ids:
                tf = self._tf.pop(cid, None)
                self._docs.pop(cid, None)
                if tf:
                    n += 1
                    for t in tf:
                        self._df[t] = max(0, self._df.get(t, 0) - 1)
            return n

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        with self._lock:
            n = max(1, len(self._docs))
            scores: dict[str, float] = {}
            for t in set(tokenize(query)):
                df = self._df.get(t, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                for cid, tf in self._tf.items():
                    f = tf.get(t, 0)
                    if not f:
                        continue
                    dl = sum(tf.values())
                    denom = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                    scores[cid] = scores.get(cid, 0.0) + idf * f * (self.k1 + 1) / denom
            ranked = sorted(scores, key=lambda c: -scores[c])[:top_k]
            return [Hit(c, self._docs[c].doc_id, self._docs[c].version,
                        self._docs[c].text, scores[c], "bm25", self._docs[c].meta, r + 1)
                    for r, c in enumerate(ranked)]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"backend": "bm25-okapi", "documents": len(self._docs),
                    "vocabulary": len(self._df), "avgdl": round(self._avgdl, 2)}


def reciprocal_rank_fusion(rank_lists: list[list[Hit]], k: int = 60,
                           top_k: int = 5) -> list[Hit]:
    """RRF 融合多路召回：score = Σ 1/(k + rank)，不要求各路分数可比。"""
    fused: dict[str, float] = {}
    merged: dict[str, Hit] = {}
    for hits in rank_lists:
        for h in hits:
            fused[h.chunk_id] = fused.get(h.chunk_id, 0.0) + 1.0 / (k + h.rank)
            if h.chunk_id not in merged:
                merged[h.chunk_id] = Hit(h.chunk_id, h.doc_id, h.version, h.text,
                                         h.score, h.source, dict(h.meta), h.rank)
            else:
                merged[h.chunk_id].source += "+" + h.source
    ordered = sorted(fused, key=lambda c: -fused[c])[:top_k]
    out = []
    for r, cid in enumerate(ordered, 1):
        h = merged[cid]
        out.append(Hit(h.chunk_id, h.doc_id, h.version, h.text,
                       fused[cid], "hybrid(" + h.source + ")", h.meta, r))
    return out


def rerank(query: str, hits: list[Hit], top_k: int = 5) -> list[Hit]:
    """特征重排：检索分 + query 词覆盖率 + 数字/金额命中 + 长度惩罚。"""
    qtoks = set(tokenize(query))
    qnums = set(re.findall(r"\d+(?:\.\d+)?", query))
    out = []
    for h in hits:
        toks = set(tokenize(h.text))
        overlap = len(qtoks & toks) / max(1, len(qtoks))
        nums = set(re.findall(r"\d+(?:\.\d+)?", h.text))
        num_hit = len(qnums & nums) / max(1, len(qnums)) if qnums else 0.0
        length_penalty = min(1.0, len(h.text) / 400.0)
        score = 0.55 * min(1.0, h.score) + 0.30 * overlap + 0.10 * num_hit + 0.05 * length_penalty
        out.append(Hit(h.chunk_id, h.doc_id, h.version, h.text, score,
                       h.source + "+rerank", h.meta, h.rank))
    out.sort(key=lambda x: -x.score)
    for i, h in enumerate(out[:top_k], 1):
        h.rank = i
    return out[:top_k]


VECTOR_DB_ADAPTERS: dict[str, dict[str, Any]] = {
    "Milvus": {"contract": "VectorStoreAdapter", "config": ["uri", "collection", "dim"],
               "note": "分布式向量库，适合大规模商品/文档向量"},
    "Qdrant": {"contract": "VectorStoreAdapter", "config": ["url", "collection", "dim"],
               "note": "支持 payload filter，适合带类目/租户过滤"},
    "Chroma": {"contract": "VectorStoreAdapter", "config": ["persist_directory", "collection"],
               "note": "轻量本地持久化"},
    "FAISS": {"contract": "VectorStoreAdapter", "config": ["index_path", "dim"],
              "note": "本地高维索引，无服务依赖"},
    "Pinecone": {"contract": "VectorStoreAdapter", "config": ["api_key", "index", "namespace"],
                 "note": "全托管，按 namespace 做多租户"},
    "Elasticsearch": {"contract": "VectorStoreAdapter + BM25",
                      "config": ["hosts", "index"], "note": "全文 + 向量混合检索一体"},
    "LlamaIndex": {"contract": "VectorStoreAdapter（经 VectorStoreIndex 包装）",
                   "config": ["storage_context"], "note": "文档索引与检索编排框架"},
}


def make_indexes() -> tuple[InMemoryVectorStore, BM25Index]:
    return InMemoryVectorStore(), BM25Index()


def hybrid_search(query: str, vector: InMemoryVectorStore, bm25: BM25Index,
                  top_k: int = 5, use_rerank: bool = True) -> dict[str, Any]:
    v_hits = vector.search(query, top_k=top_k * 2)
    b_hits = bm25.search(query, top_k=top_k * 2)
    fused = reciprocal_rank_fusion([v_hits, b_hits], top_k=top_k)
    final = rerank(query, fused, top_k=top_k) if use_rerank else fused
    return {"query": query, "vector_hits": [h.to_dict() for h in v_hits[:top_k]],
            "bm25_hits": [h.to_dict() for h in b_hits[:top_k]],
            "fused": [h.to_dict() for h in fused],
            "hits": [h.to_dict() for h in final],
            "stages": ["vector", "bm25", "rrf"] + (["rerank"] if use_rerank else [])}
