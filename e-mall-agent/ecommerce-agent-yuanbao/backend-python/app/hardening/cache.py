"""四级缓存 + 失效（总纲 4.16 / 5.8）。降本顺序第一条就是缓存，之前项目直接跳到了路由。

  exact       query -> answer
  semantic    query embedding 近邻复用（带误命中风险，需相似度阈值 + 可选人工确认）
  retrieval   query -> hits
  embedding   text -> vector
失效：文档/版本变更按 doc_id 前缀清除；TTL；显式 bump generation。
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.capabilities.rag.vectorstore import HashEmbedding


@dataclass
class Entry:
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl: float = 300.0
    generation: int = 0
    tags: tuple[str, ...] = ()

    def alive(self, gen: int) -> bool:
        return self.generation == gen and time.time() - self.created_at < self.ttl


class CacheLayer:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Entry]] = {k: {} for k in
                                                   ("exact", "semantic", "retrieval", "embedding")}
        self._gen = 0
        self._embed = HashEmbedding()
        self._lock = threading.RLock()
        self.stats_: dict[str, dict[str, int]] = {k: {"hit": 0, "miss": 0, "put": 0}
                                                  for k in self._data}

    @staticmethod
    def key(kind: str, payload: Any) -> str:
        raw = repr(payload)
        return kind + ":" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    def get(self, layer: str, payload: Any) -> tuple[bool, Any]:
        with self._lock:
            e = self._data[layer].get(self.key(layer, payload))
            if e and e.alive(self._gen):
                self.stats_[layer]["hit"] += 1
                return True, e.value
            self.stats_[layer]["miss"] += 1
            return False, None

    def put(self, layer: str, payload: Any, value: Any, ttl: float = 300.0,
            tags: tuple[str, ...] = ()) -> None:
        with self._lock:
            self._data[layer][self.key(layer, payload)] = Entry(
                value, ttl=ttl, generation=self._gen, tags=tags)
            self.stats_[layer]["put"] += 1

    def semantic_get(self, query: str, threshold: float = 0.93) -> tuple[bool, Any, float]:
        """语义缓存：相似度不足直接 miss，避免把「能退吗」命中到「怎么退」。"""
        import numpy as np
        q = self._embed.embed(query)
        best, best_sim, best_key = None, 0.0, ""
        with self._lock:
            items = list(self._data["semantic"].items())
        for k, e in items:
            if not e.alive(self._gen):
                continue
            sim = float(q @ self._embed.embed(str(e.tags[0] if e.tags else "")))
            if sim > best_sim:
                best, best_sim, best_key = e.value, sim, k
        with self._lock:
            self.stats_["semantic"]["hit" if best_sim >= threshold else "miss"] += 1
        return (best_sim >= threshold), (best if best_sim >= threshold else None), round(best_sim, 4)

    def semantic_put(self, query: str, value: Any, ttl: float = 300.0) -> None:
        self.put("semantic", query, value, ttl, tags=(query,))

    def invalidate(self, doc_id: str | None = None, all_layers: bool = False) -> dict[str, Any]:
        """知识更新必须能失效：按 tag 精确失效，或整体 generation +1。"""
        with self._lock:
            if all_layers or doc_id is None:
                self._gen += 1
                return {"strategy": "generation_bump", "generation": self._gen}
            removed = 0
            for layer, items in self._data.items():
                for k, e in list(items.items()):
                    if doc_id in e.tags:
                        del items[k]
                        removed += 1
            return {"strategy": "tag_purge", "doc_id": doc_id, "removed": removed,
                    "generation": self._gen}

    def report(self) -> dict[str, Any]:
        with self._lock:
            out = {}
            for k, s in self.stats_.items():
                total = s["hit"] + s["miss"]
                out[k] = {**s, "hit_rate": round(s["hit"] / max(1, total), 4),
                          "size": len(self._data[k])}
            return {"generation": self._gen, "layers": out}


CACHE = CacheLayer()
