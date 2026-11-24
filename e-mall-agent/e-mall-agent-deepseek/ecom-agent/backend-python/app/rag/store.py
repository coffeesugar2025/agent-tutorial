"""向量存储抽象 + Milvus 实现 + 内存/关键词降级实现。

三个语义一致的实现：
* :class:`MilvusVectorStore`：生产主路径（dense + sparse 双路检索）；
* :class:`MemoryVectorStore`：进程内降级（Milvus 不可用、CI、首次体验）；
* 关键词降级：知识块用「候选 + BM25-lite 重排」，商品表用 MySQL ngram FULLTEXT。

任何降级都会 ``record_degradation`` 打点并记日志（可观测性要求）。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-12] 检索增强 RAG
# 职责：向量存储抽象 + Milvus 实现 + 内存/关键词降级实现
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.infra.db import session_scope
from app.infra.milvus import MilvusUnavailable, milvus_gateway
from app.obs.metrics import record_degradation
from app.rag.sparse import cosine as sparse_cosine
from app.rag.sparse import overlap_score, sparse_vector

logger = logging.getLogger(__name__)


@dataclass
class VectorRecord:
    """一条待写入的向量记录。"""

    id: int
    vector: list[float]
    content: str
    payload: dict[str, Any] = field(default_factory=dict)
    sparse: dict[int, float] | None = None


@dataclass
class Hit:
    """检索命中项。"""

    id: int
    score: float
    content: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "dense"


class VectorStore(ABC):
    """向量存储接口。"""

    name: str = "base"

    @abstractmethod
    def ensure(self, collection: str, dim: int) -> None: ...

    @abstractmethod
    def upsert(self, collection: str, records: list[VectorRecord]) -> int: ...

    @abstractmethod
    def delete(self, collection: str, ids: list[int] | None = None, expr: str | None = None) -> None: ...

    @abstractmethod
    def search_dense(
        self, collection: str, vector: list[float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[Hit]: ...

    @abstractmethod
    def search_sparse(
        self, collection: str, sparse: dict[int, float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[Hit]: ...

    def health(self) -> str:
        return "UP"

    def count(self, collection: str) -> int:
        return 0


def _match(payload: dict[str, Any], filters: dict[str, Any] | None) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        actual = payload.get(key)
        if expected is None:
            continue
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


class MilvusVectorStore(VectorStore):
    """Milvus 实现（collections 由 ``ensure`` 幂等创建）。"""

    name = "milvus"

    def ensure(self, collection: str, dim: int) -> None:
        milvus_gateway.ensure_collection(collection, dim, enable_sparse=True)

    def upsert(self, collection: str, records: list[VectorRecord]) -> int:
        rows: list[dict[str, Any]] = []
        for record in records:
            sparse = record.sparse or sparse_vector(record.content)
            if not sparse:
                sparse = {0: 0.0}
            rows.append(
                {
                    "id": int(record.id),
                    "vector": [float(v) for v in record.vector],
                    "sparse": {str(k): float(v) for k, v in sparse.items()},
                    "content": record.content[:8000],
                    "payload": record.payload,
                }
            )
        return milvus_gateway.upsert(collection, rows)

    def delete(self, collection: str, ids: list[int] | None = None, expr: str | None = None) -> None:
        milvus_gateway.delete(collection, ids=ids, expr=expr)

    def search_dense(
        self, collection: str, vector: list[float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[Hit]:
        raw = milvus_gateway.search(collection, vector, top_k=top_k)
        hits = []
        for item in raw:
            entity = item.get("entity") or {}
            payload = entity.get("payload") or {}
            if not _match(payload, filters):
                continue
            hits.append(
                Hit(
                    id=int(item["id"]),
                    score=round(float(item.get("score", 0.0)), 6),
                    content=str(entity.get("content", "")),
                    payload=payload,
                    source="dense",
                )
            )
        return hits

    def search_sparse(
        self, collection: str, sparse: dict[int, float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[Hit]:
        if not sparse:
            return []
        raw = milvus_gateway.search(
            collection,
            [{str(k): float(v) for k, v in sparse.items()}],  # type: ignore[arg-type]
            top_k=top_k,
            anns_field="sparse",
        )
        hits = []
        for item in raw:
            entity = item.get("entity") or {}
            payload = entity.get("payload") or {}
            if not _match(payload, filters):
                continue
            hits.append(
                Hit(
                    id=int(item["id"]),
                    score=round(float(item.get("score", 0.0)), 6),
                    content=str(entity.get("content", "")),
                    payload=payload,
                    source="sparse",
                )
            )
        return hits

    def health(self) -> str:
        return milvus_gateway.health()

    def count(self, collection: str) -> int:
        return milvus_gateway.count(collection)


class MemoryVectorStore(VectorStore):
    """进程内向量库（余弦相似度 + 稀疏点积），线程安全。"""

    name = "memory"
    _DATA: dict[str, dict[int, VectorRecord]] = {}
    _LOCK = threading.RLock()

    def ensure(self, collection: str, dim: int) -> None:
        with self._LOCK:
            self._DATA.setdefault(collection, {})

    def upsert(self, collection: str, records: list[VectorRecord]) -> int:
        with self._LOCK:
            bucket = self._DATA.setdefault(collection, {})
            for record in records:
                if record.sparse is None:
                    record.sparse = sparse_vector(record.content)
                bucket[int(record.id)] = record
            return len(records)

    def delete(self, collection: str, ids: list[int] | None = None, expr: str | None = None) -> None:
        with self._LOCK:
            bucket = self._DATA.get(collection, {})
            if ids:
                for record_id in ids:
                    bucket.pop(int(record_id), None)
            elif expr:
                # 支持极简表达式：payload.<key> == "<value>"
                for key, value in _parse_expr(expr).items():
                    for record_id, record in list(bucket.items()):
                        if record.payload.get(key) != value:
                            bucket.pop(record_id, None)

    def search_dense(
        self, collection: str, vector: list[float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[Hit]:
        with self._LOCK:
            records = list(self._DATA.get(collection, {}).values())
        hits: list[Hit] = []
        for record in records:
            if not _match(record.payload, filters):
                continue
            hits.append(
                Hit(
                    id=record.id,
                    score=round(_cosine_dense(vector, record.vector), 6),
                    content=record.content,
                    payload=record.payload,
                    source="dense",
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    def search_sparse(
        self, collection: str, sparse: dict[int, float], top_k: int = 10, filters: dict[str, Any] | None = None
    ) -> list[Hit]:
        with self._LOCK:
            records = list(self._DATA.get(collection, {}).values())
        hits: list[Hit] = []
        for record in records:
            if not _match(record.payload, filters):
                continue
            record_sparse = record.sparse if record.sparse is not None else sparse_vector(record.content)
            hits.append(
                Hit(
                    id=record.id,
                    score=round(sparse_cosine(sparse, record_sparse), 6),
                    content=record.content,
                    payload=record.payload,
                    source="sparse",
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]

    def count(self, collection: str) -> int:
        with self._LOCK:
            return len(self._DATA.get(collection, {}))

    def clear(self) -> None:
        with self._LOCK:
            self._DATA.clear()


def _cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    length = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(length))
    norm_a = math.sqrt(sum(value * value for value in a[:length]))
    norm_b = math.sqrt(sum(value * value for value in b[:length]))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _parse_expr(expr: str) -> dict[str, Any]:
    """解析 ``payload.doc_type == "POLICY"`` 这类极简表达式。"""
    import re

    result: dict[str, Any] = {}
    for key, value in re.findall(r'payload\.(\w+)\s*==\s*"([^"]*)"', expr):
        result[key] = value
    return result


memory_store = MemoryVectorStore()
milvus_store = MilvusVectorStore()


# ──────── [CAP-12] 检索增强 RAG ────────
#   本处：向量库选择（Milvus / 内存，含降级）
#   域约束：任一环节失败必须降级并标记 degraded，不允许静默返回空结果
def get_store(force: str | None = None) -> VectorStore:
    """按配置返回存储实现；``auto`` 优先 Milvus，失败降级内存。"""
    mode = (force or settings.vector_store or "auto").lower()
    if mode == "memory":
        return memory_store
    if mode == "milvus":
        return milvus_store
    if milvus_gateway.available():
        return milvus_store
    record_degradation("vector_store", "milvus_unavailable_use_memory")
    return memory_store


def reset_stores() -> None:
    """测试用：清空内存向量库与 Milvus 冷却状态。"""
    memory_store.clear()
    milvus_gateway.reset()


# ---------------------------------------------------------------------------
# 关键词降级检索
# ---------------------------------------------------------------------------
def keyword_search_chunks(
    query: str,
    top_k: int = 10,
    doc_types: list[str] | None = None,
    visibility: str | None = "PUBLIC",
) -> list[Hit]:
    """知识块关键词降级：候选集 + BM25-lite 覆盖率重排。

    说明：``01-schema.sql`` 未给 ``knowledge_chunk`` 建 FULLTEXT 索引，
    这里用 LIKE 取候选（最多 500 条）后本地重排，召回质量与 ngram 全文检索接近。
    """
    terms = _query_terms(query)
    if not terms:
        return []
    try:
        with session_scope() as db:
            sql = [
                "SELECT c.id, c.content, c.parent_content, c.document_id,",
                "d.title, d.doc_type, d.visibility",
                "FROM knowledge_chunk c JOIN knowledge_document d ON d.id = c.document_id",
                "WHERE d.deleted_at IS NULL AND d.status = 'READY'",
            ]
            params: dict[str, Any] = {}
            if visibility:
                sql.append("AND d.visibility = :visibility")
                params["visibility"] = visibility
            if doc_types:
                placeholders = []
                for index, doc_type in enumerate(doc_types):
                    key = f"dt{index}"
                    placeholders.append(f":{key}")
                    params[key] = doc_type
                sql.append(f"AND d.doc_type IN ({', '.join(placeholders)})")
            like_clauses = []
            for index, term in enumerate(terms[:8]):
                key = f"kw{index}"
                like_clauses.append(f"c.content LIKE :{key}")
                params[key] = f"%{term}%"
            sql.append(f"AND ({' OR '.join(like_clauses)})")
            sql.append("LIMIT 500")
            rows = db.execute(text(" ".join(sql)), params).mappings().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("关键词降级检索失败: %s", exc)
        return []

    hits: list[Hit] = []
    for row in rows:
        content = str(row["content"] or "")
        score = round(overlap_score(query, content) * 0.85 + 0.05, 6)
        hits.append(
            Hit(
                id=int(row["id"]),
                score=score,
                content=content,
                payload={
                    "chunk_id": int(row["id"]),
                    "document_id": int(row["document_id"]),
                    "title": row["title"],
                    "doc_type": row["doc_type"],
                    "visibility": row["visibility"],
                    "parent_content": row["parent_content"],
                },
                source="keyword",
            )
        )
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits[:top_k]


def product_fulltext_search(query: str, top_k: int = 10) -> list[Hit]:
    """商品全文检索：MySQL 走 ngram FULLTEXT，其它方言退化为 LIKE + 重排。"""
    terms = _query_terms(query)
    if not terms:
        return []
    with session_scope() as db:
        dialect = getattr(getattr(db.get_bind(), "dialect", None), "name", "")
        rows: list[Any]
        try:
            if dialect == "mysql":
                rows = db.execute(
                    text(
                        "SELECT id, sku, title, brand, price, rating, sales, search_text "
                        "FROM product WHERE status = 1 AND MATCH(title, subtitle, brand, search_text) "
                        "AGAINST (:q IN NATURAL LANGUAGE MODE) LIMIT :limit"
                    ),
                    {"q": query, "limit": top_k * 3},
                ).mappings().all()
            else:
                like = f"%{terms[0]}%"
                rows = db.execute(
                    text(
                        "SELECT id, sku, title, brand, price, rating, sales, search_text "
                        "FROM product WHERE status = 1 AND (title LIKE :like OR search_text LIKE :like) "
                        "LIMIT :limit"
                    ),
                    {"like": like, "limit": top_k * 3},
                ).mappings().all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("商品全文检索失败: %s", exc)
            return []
    hits = [
        Hit(
            id=int(row["id"]),
            score=round(overlap_score(query, f"{row['title']} {row['search_text'] or ''}"), 6),
            content=f"{row['title']} {row['brand'] or ''}",
            payload={"sku": row["sku"], "title": row["title"], "price": float(row["price"])},
            source="fulltext",
        )
        for row in rows
    ]
    hits.sort(key=lambda item: item.score, reverse=True)
    return hits[:top_k]


def _query_terms(query: str) -> list[str]:
    import re

    if not query:
        return []
    cjk = re.findall(r"[\u4e00-\u9fff]{2,6}", query)
    ascii_terms = re.findall(r"[A-Za-z0-9]{2,}", query)
    terms = [*cjk, *ascii_terms]
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return unique


__all__ = [
    "Hit",
    "MemoryVectorStore",
    "MilvusUnavailable",
    "MilvusVectorStore",
    "VectorRecord",
    "VectorStore",
    "get_store",
    "keyword_search_chunks",
    "memory_store",
    "milvus_store",
    "product_fulltext_search",
    "reset_stores",
]
