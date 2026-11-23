"""语义缓存：以 query embedding 的相似度命中，支持阈值与 TTL。

复用现有 ``HashEmbeddings``，无需外部向量库或 Redis。缓存条目含命中次数与
创建时间，``clock`` 可注入以便确定性地验证 TTL 过期。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .embeddings import HashEmbeddings


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（HashEmbeddings 向量已归一化，点积即余弦）。"""
    if not a or not b:
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


@dataclass
class CachedAnswer:
    """一条缓存答案。"""

    query: str
    answer: Any
    embedding: list[float] = field(default_factory=list, repr=False)
    created_at: float = 0.0
    hits: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, ttl_seconds: float | None, now: float) -> bool:
        """TTL <= 0 表示永不过期。"""
        if ttl_seconds is None or ttl_seconds <= 0:
            return False
        return now - self.created_at >= ttl_seconds


class SemanticCache:
    """按查询语义相似度缓存答案的有界缓存。"""

    def __init__(
        self,
        threshold: float = 0.92,
        ttl_seconds: float = 300.0,
        embeddings: HashEmbeddings | None = None,
        max_size: int = 256,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold 必须在 [0, 1] 之间")
        if max_size < 1:
            raise ValueError("max_size 必须 >= 1")
        self.threshold = threshold
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._embeddings = embeddings or HashEmbeddings()
        self._clock = clock or time.time
        self._entries: dict[str, CachedAnswer] = {}
        self._seq = 0
        self._hits = 0
        self._misses = 0

    def _evict_expired(self, now: float) -> None:
        for key in [k for k, v in self._entries.items()
                    if v.is_expired(self.ttl_seconds, now)]:
            del self._entries[key]

    def get(self, query: str) -> CachedAnswer | None:
        """查找最相似且未过期的条目；命中时增加其命中计数并返回。"""
        now = self._clock()
        self._evict_expired(now)
        vector = self._embeddings.embed_query(query)
        best: CachedAnswer | None = None
        best_score = -1.0
        for entry in self._entries.values():
            score = _cosine(vector, entry.embedding)
            if score > best_score:
                best, best_score = entry, score
        if best is not None and best_score >= self.threshold:
            best.hits += 1
            self._hits += 1
            return best
        self._misses += 1
        return None

    def put(self, query: str, answer: Any,
            metadata: Mapping[str, Any] | None = None) -> CachedAnswer:
        """写入答案（相同 query 视为新条目），超出容量时淘汰最早条目。"""
        now = self._clock()
        self._evict_expired(now)
        self._seq += 1
        entry = CachedAnswer(
            query=query,
            answer=answer,
            embedding=self._embeddings.embed_query(query),
            created_at=now,
            metadata=dict(metadata or {}),
        )
        self._entries[str(self._seq)] = entry
        while len(self._entries) > self.max_size:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        return entry

    def clear(self) -> None:
        self._entries.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, Any]:
        return {"size": len(self._entries), "hits": self._hits, "misses": self._misses}

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["CachedAnswer", "SemanticCache"]
