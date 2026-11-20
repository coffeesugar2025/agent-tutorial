"""教学用极简向量库：纯 Python 余弦相似度 + JSON 持久化。

生产替换清单（接口保持一致，Demo 代码不用改）：
  Chroma        -> 本地嵌入式、适合原型
  Qdrant        -> 支持 payload 过滤、混合检索
  Milvus        -> 大规模、分布式
  FAISS         -> 纯索引库，需自己管元数据
  Pinecone      -> 全托管
  Elasticsearch -> 同时做 BM25 + 向量（第 8 章混合检索的生产形态）

关键接口：add / search / delete / save / load —— 这就是"向量库适配器"的全部。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import config


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class VectorStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config.VECTOR_PATH
        self.items: list[dict] = []   # {id, text, vector, metadata}
        if self.path.exists():
            self.load()

    def add(self, id_: str, text: str, vector: list[float], metadata: dict | None = None) -> None:
        self.items = [x for x in self.items if x["id"] != id_]
        self.items.append({"id": id_, "text": text, "vector": vector, "metadata": metadata or {}})

    def delete(self, id_: str | None = None, *, where: dict | None = None) -> int:
        """撤销 / 知识下线：按 id 或 metadata 条件删除。"""
        before = len(self.items)
        if id_:
            self.items = [x for x in self.items if x["id"] != id_]
        if where:
            self.items = [x for x in self.items
                          if not all(x["metadata"].get(k) == v for k, v in where.items())]
        return before - len(self.items)

    def search(self, query_vector: list[float], top_k: int = 5,
               *, where: dict | None = None) -> list[dict]:
        pool = [x for x in self.items
                if not where or all(x["metadata"].get(k) == v for k, v in where.items())]
        scored = [{"id": x["id"], "text": x["text"], "metadata": x["metadata"],
                   "score": cosine(query_vector, x["vector"])} for x in pool]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def save(self) -> None:
        config.ensure_dirs()
        self.path.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")

    def load(self) -> None:
        try:
            self.items = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self.items = []

    def __len__(self) -> int:
        return len(self.items)


def rrf_fuse(rankings: list[list[dict]], *, k: int = 60, top_k: int = 5) -> list[dict]:
    """Reciprocal Rank Fusion：把 BM25 / 向量 / 图检索的多路结果融合，无需调权重。"""
    fused: dict[str, dict] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            key = item["id"]
            entry = fused.setdefault(key, {"id": key, "text": item.get("text", ""),
                                           "metadata": item.get("metadata", {}),
                                           "rrf": 0.0, "sources": []})
            entry["rrf"] += 1.0 / (k + rank)
            entry["sources"].append(item.get("source", "unknown"))
            entry.setdefault("raw", {})[item.get("source", "unknown")] = item.get("score", 0)
    out = sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)
    return out[:top_k]
