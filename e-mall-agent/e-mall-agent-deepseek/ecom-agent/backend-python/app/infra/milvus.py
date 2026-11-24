"""Milvus 封装（pymilvus 2.5+ 的 MilvusClient 高层 API）。

三个集合（前缀 ``MILVUS_COLLECTION_PREFIX``）：
* ``ecom_knowledge``：知识切片，dense + sparse 双向量，支持 visibility/doc_type 过滤；
* ``ecom_product``：商品语义向量（导购召回）；
* ``ecom_memory``：用户长期记忆。

Milvus 不可用时抛 :class:`MilvusUnavailable`，由 ``rag.store`` 捕获并降级到
内存向量 / MySQL FULLTEXT；本模块只负责"能不能用"与"怎么读写"。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-14] 可靠性/降级
# 职责：Milvus 封装（pymilvus 2
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.config import settings
from app.obs.metrics import record_degradation

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于运行环境
    from pymilvus import DataType, MilvusClient

    PYMILVUS_AVAILABLE = True
except Exception:  # noqa: BLE001
    DataType = None  # type: ignore[assignment]
    MilvusClient = None  # type: ignore[assignment]
    PYMILVUS_AVAILABLE = False

_COOLDOWN_SECONDS = 30.0
VARCHAR_MAX = 8192


class MilvusUnavailable(RuntimeError):
    """Milvus 不可用（连接失败 / 集合操作失败 / 未安装 pymilvus）。"""


class MilvusGateway:
    """Milvus 连接与集合操作的薄封装（懒连接 + 冷却期 + 统一异常）。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._lock = threading.Lock()
        self._down_until = 0.0
        self._warned = False

    # --- 连接 ---------------------------------------------------------------
    def _mark_down(self, reason: str) -> None:
        self._down_until = time.time() + _COOLDOWN_SECONDS
        if not self._warned:
            self._warned = True
            record_degradation("milvus", reason)
        self._client = None

    def client(self) -> Any:
        if not PYMILVUS_AVAILABLE:
            raise MilvusUnavailable("pymilvus 未安装")
        if time.time() < self._down_until:
            raise MilvusUnavailable("Milvus 处于冷却期")
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                client = MilvusClient(uri=settings.milvus_uri)
                client.list_collections()
                self._client = client
                self._warned = False
                logger.info("Milvus 已连接 %s", settings.milvus_uri)
                return client
            except Exception as exc:  # noqa: BLE001
                self._mark_down(f"connect:{type(exc).__name__}")
                raise MilvusUnavailable(str(exc)) from exc

    def available(self) -> bool:
        try:
            self.client()
            return True
        except MilvusUnavailable:
            return False

    # --- 集合 ---------------------------------------------------------------
    def has_collection(self, name: str) -> bool:
        try:
            return bool(self.client().has_collection(collection_name=name))
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._mark_down(f"has_collection:{type(exc).__name__}")
            raise MilvusUnavailable(str(exc)) from exc

    def ensure_collection(self, name: str, dim: int, enable_sparse: bool = True) -> None:
        """幂等创建集合：主键 id(INT64)、dense 向量、可选 sparse、content、payload(JSON)。"""
        client = self.client()
        if self.has_collection(name):
            return
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        if enable_sparse:
            schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("content", DataType.VARCHAR, max_length=VARCHAR_MAX)
        schema.add_field("payload", DataType.JSON)
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        if enable_sparse:
            index_params.add_index(
                field_name="sparse",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
            )
        client.create_collection(collection_name=name, schema=schema, index_params=index_params)
        logger.info("已创建 Milvus 集合 %s dim=%s sparse=%s", name, dim, enable_sparse)

    # --- 写入 ---------------------------------------------------------------
    def upsert(self, name: str, rows: list[dict[str, Any]]) -> int:
        """批量写入（主键存在则覆盖），返回行数。"""
        if not rows:
            return 0
        try:
            self.client().upsert(collection_name=name, data=rows)
            return len(rows)
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._mark_down(f"upsert:{type(exc).__name__}")
            raise MilvusUnavailable(str(exc)) from exc

    def delete(self, name: str, ids: list[int] | None = None, expr: str | None = None) -> None:
        """按主键或过滤表达式删除。"""
        if not ids and not expr:
            return
        try:
            client = self.client()
            if ids:
                client.delete(collection_name=name, ids=ids)
            elif expr:
                client.delete(collection_name=name, filter=expr)
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._mark_down(f"delete:{type(exc).__name__}")
            raise MilvusUnavailable(str(exc)) from exc

    def drop(self, name: str) -> None:
        try:
            if self.has_collection(name):
                self.client().drop_collection(collection_name=name)
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MilvusUnavailable(str(exc)) from exc

    # --- 检索 ---------------------------------------------------------------
    def search(
        self,
        name: str,
        vector: list[float],
        top_k: int = 10,
        expr: str | None = None,
        output_fields: list[str] | None = None,
        anns_field: str = "vector",
    ) -> list[dict[str, Any]]:
        """向量检索，统一返回 ``[{"id","score","entity"}]``（score 越大越相似）。"""
        try:
            results = self.client().search(
                collection_name=name,
                data=[vector],
                anns_field=anns_field,
                limit=top_k,
                filter=expr,
                output_fields=output_fields or ["content", "payload"],
                search_params={"metric_type": "COSINE" if anns_field == "vector" else "IP"},
            )
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._mark_down(f"search:{type(exc).__name__}")
            raise MilvusUnavailable(str(exc)) from exc
        hits: list[dict[str, Any]] = []
        for group in results or []:
            for hit in group:
                hits.append(
                    {
                        "id": hit.get("id"),
                        "score": float(hit.get("distance", 0.0)),
                        "entity": hit.get("entity", {}) or {},
                    }
                )
        return hits

    def query(self, name: str, expr: str, output_fields: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """标量过滤查询（少量调试/校验用）。"""
        try:
            return list(
                self.client().query(
                    collection_name=name,
                    filter=expr,
                    output_fields=output_fields or ["content", "payload"],
                    limit=limit,
                )
            )
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            self._mark_down(f"query:{type(exc).__name__}")
            raise MilvusUnavailable(str(exc)) from exc

    def count(self, name: str) -> int:
        try:
            stats = self.client().get_collection_stats(collection_name=name)
            return int(stats.get("row_count", 0))
        except Exception:  # noqa: BLE001
            return 0

    # --- 运维 ---------------------------------------------------------------
    def health(self) -> str:
        return "UP" if self.available() else "DOWN"

    def reset(self) -> None:
        """测试用：清空连接与冷却状态。"""
        with self._lock:
            self._client = None
            self._down_until = 0.0
            self._warned = False


milvus_gateway = MilvusGateway()

__all__ = ["PYMILVUS_AVAILABLE", "MilvusGateway", "MilvusUnavailable", "milvus_gateway"]
