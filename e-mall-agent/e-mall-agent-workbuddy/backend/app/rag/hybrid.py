"""混合检索（RAG 进阶层）：BM25 + 向量召回 + RRF 融合 + 确定性重排。

- ``BM25Index``：纯 Python BM25，中文按 bigram 切词，不依赖 Elasticsearch。
- ``HybridRetriever``：复用 ``HashEmbeddings`` + ``InMemoryVectorStore``，与 BM25
  用 RRF（Reciprocal Rank Fusion）融合，支持通道权重；无命中时真实返回空列表，
  不注入任何兜底假数据。
- ``Reranker``：词面覆盖率 + 位置 + 元数据加权的交叉特征重排。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from langchain_core.vectorstores import InMemoryVectorStore

from .embeddings import HashEmbeddings

_LATIN = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def bm25_tokenize(text: str) -> list[str]:
    """BM25 切词：中文 bigram（单字成串时保留单字），拉丁词整词保留。"""
    text = (text or "").lower()
    tokens: list[str] = _LATIN.findall(text)
    for run in _CJK.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


# ---------------------------------------------------------------------------
# 结果结构
# ---------------------------------------------------------------------------
@dataclass
class SourceDetail:
    """某一召回通道的明细。"""

    channel: str
    rank: int = 0
    raw_score: float = 0.0
    contribution: float = 0.0


@dataclass
class RetrievedChunk:
    """带融合分数与来源明细的检索结果。"""

    id: str
    doc_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    rank: int = 0
    sources: dict[str, SourceDetail] = field(default_factory=dict)

    def reranked(self, score: float, detail: SourceDetail) -> "RetrievedChunk":
        """返回一个带重排分数的新实例（保留各召回通道明细）。"""
        sources = dict(self.sources)
        sources["rerank"] = detail
        return RetrievedChunk(
            id=self.id, doc_id=self.doc_id, content=self.content,
            metadata=dict(self.metadata), score=score, rank=self.rank,
            sources=sources,
        )


@dataclass
class _IndexedDoc:
    doc_id: str
    content: str
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------
@dataclass
class BM25Hit:
    doc_id: str
    content: str
    metadata: dict[str, Any]
    score: float


class BM25Index:
    """经典 BM25（Okapi）：纯 Python 实现，支持增量写入。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 要求 k1 > 0 且 0 <= b <= 1")
        self.k1 = k1
        self.b = b
        self._docs: list[BM25Hit] = []
        self._doc_ids: set[str] = set()
        self._term_freq: list[Counter[str]] = []
        self._doc_len: list[int] = []
        self._avgdl = 0.0
        self._postings: dict[str, list[tuple[int, int]]] = {}

    def __len__(self) -> int:
        return len(self._docs)

    def add(self, texts: Iterable[str], metadatas: Iterable[dict[str, Any]] | None = None,
            ids: Iterable[str] | None = None) -> int:
        """增量写入文档，返回实际新增条数（重复 id 被跳过）。"""
        texts = list(texts)
        metadatas = list(metadatas) if metadatas is not None else [{} for _ in texts]
        ids = list(ids) if ids is not None else [f"doc-{len(self._docs) + i}"
                                                 for i in range(len(texts))]
        if not (len(texts) == len(metadatas) == len(ids)):
            raise ValueError("texts / metadatas / ids 长度必须一致")

        added = 0
        for text, meta, doc_id in zip(texts, metadatas, ids):
            doc_id = str(doc_id)
            if doc_id in self._doc_ids:
                continue
            tokens = bm25_tokenize(text)
            tf = Counter(tokens)
            index = len(self._docs)
            self._docs.append(BM25Hit(doc_id, text, dict(meta), 0.0))
            self._doc_ids.add(doc_id)
            self._term_freq.append(tf)
            self._doc_len.append(len(tokens))
            for term, freq in tf.items():
                self._postings.setdefault(term, []).append((index, freq))
            added += 1
        self._avgdl = sum(self._doc_len) / len(self._doc_len) if self._doc_len else 0.0
        return added

    def search(self, query: str, top_k: int = 10) -> list[BM25Hit]:
        """按 BM25 分数降序返回命中；查询无词命中时返回空。"""
        if not self._docs:
            return []
        query_terms = bm25_tokenize(query)
        if not query_terms:
            return []
        n_docs = len(self._docs)
        scores: dict[int, float] = {}
        avgdl = self._avgdl or 1.0
        for term, qtf in Counter(query_terms).items():
            postings = self._postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for index, tf in postings:
                dl = self._doc_len[index]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / avgdl)
                scores[index] = scores.get(index, 0.0) + qtf * idf * tf * (self.k1 + 1) / denom
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [
            BM25Hit(self._docs[i].doc_id, self._docs[i].content,
                    dict(self._docs[i].metadata), score)
            for i, score in ranked[:top_k]
        ]


# ---------------------------------------------------------------------------
# 混合检索
# ---------------------------------------------------------------------------
class HybridRetriever:
    """向量召回 + BM25，经 RRF 融合得到带来源明细的 ``RetrievedChunk``。"""

    def __init__(
        self,
        documents: list[dict[str, Any]] | None = None,
        *,
        top_k: int = 5,
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0,
        rrf_k: int = 60,
        min_vector_score: float = 0.2,
        embeddings: HashEmbeddings | None = None,
    ) -> None:
        if rrf_k < 0:
            raise ValueError("rrf_k 不能为负")
        self.top_k = top_k
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.rrf_k = rrf_k
        self.min_vector_score = min_vector_score
        self.store = InMemoryVectorStore(embeddings or HashEmbeddings())
        self.bm25 = BM25Index()
        self._docs: dict[str, _IndexedDoc] = {}
        self._order: list[str] = []
        if documents:
            self.add_documents(documents)

    def __len__(self) -> int:
        return len(self._docs)

    def add_documents(self, documents: list[dict[str, Any]]) -> int:
        """写入文档。每条至少含 ``content``，可选 ``id`` / ``metadata``。"""
        texts: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []
        for doc in documents:
            if isinstance(doc, str):
                doc = {"content": doc}
            doc_id = str(doc.get("id") or f"doc-{len(self._order)}")
            if doc_id in self._docs:
                continue
            content = str(doc.get("content", ""))
            meta = {**(doc.get("metadata") or {}), "doc_id": doc_id}
            self._docs[doc_id] = _IndexedDoc(doc_id, content, meta)
            self._order.append(doc_id)
            texts.append(content)
            metadatas.append(meta)
            ids.append(doc_id)
        if not texts:
            return 0
        self.bm25.add(texts, metadatas=metadatas, ids=ids)
        self.store.add_texts(texts, metadatas=metadatas)
        return len(texts)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        category: str | None = None,
        weights: tuple[float, float] | None = None,
    ) -> list[RetrievedChunk]:
        """检索。空索引或无有效命中时返回 ``[]``（不返回兜底假数据）。"""
        if not self._docs:
            return []
        k = top_k or self.top_k
        if k <= 0:
            return []
        recall_k = max(k * 3, 10)
        w_vector, w_bm25 = weights if weights is not None else (
            self.vector_weight, self.bm25_weight)

        def allowed(doc_id: str) -> bool:
            if category is None:
                return True
            return self._docs[doc_id].metadata.get("category") == category

        # 通道 1：向量召回（按余弦分排序，低分视为噪声丢弃）
        vector_channel: list[tuple[str, float, int]] = []
        try:
            pairs = self.store.similarity_search_with_score(query or " ", k=recall_k)
        except Exception:  # 向量库不可用时退化为纯 BM25
            pairs = []
        for rank, (document, score) in enumerate(pairs, start=1):
            doc_id = (document.metadata or {}).get("doc_id")
            if doc_id not in self._docs or not allowed(doc_id):
                continue
            if float(score) >= self.min_vector_score:
                vector_channel.append((doc_id, float(score), rank))

        # 通道 2：BM25
        bm25_channel: list[tuple[str, float, int]] = []
        for rank, hit in enumerate(self.bm25.search(query, recall_k), start=1):
            if hit.doc_id in self._docs and allowed(hit.doc_id):
                bm25_channel.append((hit.doc_id, hit.score, rank))

        if not vector_channel and not bm25_channel:
            return []

        fused: dict[str, float] = {}
        details: dict[str, dict[str, SourceDetail]] = {}
        # 权重为 0 的通道完全不参与候选集合，避免出现 0 分结果
        if w_vector > 0:
            for doc_id, score, rank in vector_channel:
                contribution = w_vector / (self.rrf_k + rank)
                fused[doc_id] = fused.get(doc_id, 0.0) + contribution
                details.setdefault(doc_id, {})["vector"] = SourceDetail(
                    "vector", rank, score, contribution)
        if w_bm25 > 0:
            for doc_id, score, rank in bm25_channel:
                contribution = w_bm25 / (self.rrf_k + rank)
                fused[doc_id] = fused.get(doc_id, 0.0) + contribution
                details.setdefault(doc_id, {})["bm25"] = SourceDetail(
                    "bm25", rank, score, contribution)

        ranked_ids = sorted(fused, key=lambda d: (-fused[d], self._order.index(d)))
        results: list[RetrievedChunk] = []
        for rank, doc_id in enumerate(ranked_ids[:k], start=1):
            doc = self._docs[doc_id]
            sources = dict(details[doc_id])
            sources["fused"] = SourceDetail("fused", rank, fused[doc_id], fused[doc_id])
            results.append(RetrievedChunk(
                id=doc_id, doc_id=doc_id, content=doc.content,
                metadata=dict(doc.metadata), score=fused[doc_id], rank=rank,
                sources=sources,
            ))
        return results

    def as_context(self, query: str, top_k: int | None = None) -> str:
        """渲染成可注入 prompt 的上下文。"""
        return "\n".join(
            f"[{c.metadata.get('source', c.doc_id)}] {c.content}"
            for c in self.search(query, top_k)
        )


# ---------------------------------------------------------------------------
# 重排
# ---------------------------------------------------------------------------
_DEFAULT_META_WEIGHTS: dict[str, float] = {
    "source": 0.3, "category": 0.15, "heading": 0.2, "heading_title": 0.2,
}


class Reranker:
    """确定性交叉特征重排：词面覆盖 + 位置 + 元数据加权。

    ``score = coverage_weight * coverage + position_weight * pos + metadata_weight * meta``
    不依赖任何外部模型，同一查询与候选集永远得到同一排序。
    """

    def __init__(
        self,
        query: str,
        *,
        metadata_weights: dict[str, float] | None = None,
        coverage_weight: float = 1.0,
        position_weight: float = 0.05,
        metadata_score_weight: float = 0.25,
    ) -> None:
        self.query_tokens = bm25_tokenize(query)
        self._query_total = sum(len(t) for t in self.query_tokens) or 1
        self.metadata_weights = (
            _DEFAULT_META_WEIGHTS if metadata_weights is None else metadata_weights
        )
        self.coverage_weight = coverage_weight
        self.position_weight = position_weight
        self.metadata_score_weight = metadata_score_weight

    def coverage(self, text: str) -> float:
        """按 token 长度加权的查询词覆盖率（0-1）。"""
        if not self.query_tokens:
            return 0.0
        doc_tokens = set(bm25_tokenize(text))
        covered = sum(len(t) for t in set(self.query_tokens) if t in doc_tokens)
        return min(1.0, covered / self._query_total)

    def metadata_bonus(self, metadata: dict[str, Any]) -> float:
        query_tokens = set(self.query_tokens)
        bonus = 0.0
        for key, weight in self.metadata_weights.items():
            value = str(metadata.get(key, ""))
            if value and any(t in query_tokens for t in bm25_tokenize(value)):
                bonus += weight
        return min(1.0, bonus)

    def rerank(self, chunks: list[RetrievedChunk], top_k: int | None = None) -> list[RetrievedChunk]:
        """重排并返回新实例（不修改输入），分数与重排明细写回 ``sources``。"""
        scored: list[tuple[float, int, RetrievedChunk]] = []
        for index, chunk in enumerate(chunks):
            coverage = self.coverage(chunk.content)
            position = 1.0 / (1.0 + index)
            meta = self.metadata_bonus(chunk.metadata)
            score = (self.coverage_weight * coverage
                     + self.position_weight * position
                     + self.metadata_score_weight * meta)
            reranked = chunk.reranked(score, SourceDetail(
                "rerank", 0, score, score,
            ))
            detail = reranked.sources["rerank"]
            detail.channel = "rerank"
            detail.rank = 0
            scored.append((score, -index, reranked))
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = [item[2] for item in scored]
        for rank, chunk in enumerate(results, start=1):
            chunk.rank = rank
            chunk.sources["rerank"].rank = rank
        return results[:top_k] if top_k is not None else results
