"""四个基础设施适配器 + 进程内降级实现（接口即契约）。

  VectorStoreAdapter  Milvus ↔ InMemoryVectorStore
  RelationalStore     MySQL(SQLAlchemy) ↔ sqlite3 内存
  KVStore             Redis ↔ dict + TTL
  MessageBus          RabbitMQ(pika) ↔ queue.Queue

Java 侧 backend-java 实现同一份适配器契约，见 docs/04-双后端契约.md。
"""
from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from typing import Any, Protocol

from app.infra.settings import S


class VectorStoreAdapter(Protocol):
    def upsert(self, chunks: list[dict[str, Any]]) -> int: ...
    def search(self, vector: list[float], expr: str, top_k: int) -> list[dict[str, Any]]: ...
    def delete(self, chunk_ids: list[str]) -> int: ...
    def stats(self) -> dict[str, Any]: ...


class LocalVectorAdapter:
    """进程内降级：直接复用 capabilities.rag.vectorstore 的 numpy 实现。"""
    def __init__(self) -> None:
        from app.capabilities.rag.vectorstore import InMemoryVectorStore
        self._impl = InMemoryVectorStore()
        self._rows: dict[str, dict[str, Any]] = {}

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        from app.capabilities.rag.chunking import Chunk
        objs = [Chunk(c["chunk_id"], c["doc_id"], c.get("version", 1), c["text"],
                      c.get("start", 0), c.get("end", len(c["text"])), len(c["text"]),
                      c.get("meta", {})) for c in chunks]
        self._impl.upsert(objs)
        for c in chunks:
            self._rows[c["chunk_id"]] = c
        return len(chunks)

    def search(self, vector: list[float], expr: str, top_k: int) -> list[dict[str, Any]]:
        hits = self._impl.search(" ".join(str(x) for x in vector[:8]), top_k=top_k)
        return [{"chunk_id": h.chunk_id, "doc_id": h.doc_id, "text": h.text,
                 "score": h.score, "meta": h.meta} for h in hits]

    def delete(self, chunk_ids: list[str]) -> int:
        n = self._impl.delete(chunk_ids)
        for c in chunk_ids:
            self._rows.pop(c, None)
        return n

    def stats(self) -> dict[str, Any]:
        return {"backend": "local-fallback", **self._impl.stats()}


class MilvusAdapter:
    """真实 Milvus：pymilvus 可用且 USE_EXTERNAL_INFRA=1 时启用；否则降级。

    检索前用 acl_milvus_expr 下推标量过滤（先过滤再检索）。
    """
    def __init__(self) -> None:
        self._client = None
        self._last_error = ""
        self._fallback = LocalVectorAdapter()
        if S.use_external:
            try:
                from pymilvus import MilvusClient
                client = MilvusClient(uri=f"http://{S.milvus_host}:{S.milvus_port}")
                client.list_collections()          # 真探活：连不上就降级，别等 search 时才炸
                self._client = client
                self._last_error = ""
            except Exception as exc:
                self._client = None
                self._last_error = f"{type(exc).__name__}: {exc}"

    @property
    def active_backend(self) -> str:
        return "milvus" if self._client else "local-fallback"

    def ensure_collection(self) -> dict[str, Any]:
        if not self._client:
            return {"ok": True, "backend": "local-fallback", "created": False}
        from pymilvus import DataType
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=160, is_primary=True)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=128)
        schema.add_field("version", DataType.INT64)
        schema.add_field("text", DataType.VARCHAR, max_length=4096)
        schema.add_field("acl_tenant", DataType.VARCHAR, max_length=64)
        schema.add_field("acl_roles", DataType.VARCHAR, max_length=255)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=1024)
        idx = self._client.prepare_index_params()
        idx.add_index(field_name="embedding", index_type="HNSW",
                      metric_type="COSINE", params={"M": 16, "efConstruction": 200})
        if not self._client.has_collection(S.milvus_collection):
            self._client.create_collection(S.milvus_collection, schema=schema, index_params=idx)
        return {"ok": True, "backend": "milvus", "collection": S.milvus_collection,
                "index": "HNSW/M=16/efConstruction=200"}

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        if not self._client:
            return self._fallback.upsert(chunks)
        try:
            return self._upsert_remote(chunks)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return self._fallback.upsert(chunks)

    def _upsert_remote(self, chunks: list[dict[str, Any]]) -> int:
        rows = [{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"],
                 "version": c.get("version", 1), "text": c["text"][:4000],
                 "acl_tenant": c.get("meta", {}).get("acl_tenant", "t_default"),
                 "acl_roles": ",".join(c.get("meta", {}).get("acl_roles", ["user"])),
                 "embedding": c.get("embedding", [0.0] * 1024)} for c in chunks]
        self._client.upsert(S.milvus_collection, rows)
        return len(rows)

    def search(self, vector: list[float], expr: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self._client:
            return self._fallback.search(vector, expr, top_k)
        try:
            res = self._client.search(S.milvus_collection, data=[vector], filter=expr,
                                  limit=top_k, output_fields=["chunk_id", "doc_id", "text", "acl_tenant"],
                                  search_params={"metric_type": "COSINE", "params": {"ef": 64}})
            return [{"chunk_id": h["id"], **h["entity"]} for h in res[0]]
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return self._fallback.search(vector, expr, top_k)

    def delete(self, chunk_ids: list[str]) -> int:
        if not self._client:
            return self._fallback.delete(chunk_ids)
        try:
            self._client.delete(S.milvus_collection, ids=chunk_ids)
            return len(chunk_ids)
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return self._fallback.delete(chunk_ids)

    def stats(self) -> dict[str, Any]:
        return {**self._fallback.stats(), "backend": self.active_backend,
                "last_error": self._last_error[:160]}


class RelationalStore:
    """MySQL(SQLAlchemy) ↔ sqlite 内存；表结构与 infra/mysql/init/01-schema.sql 对齐（子集）。"""
    def __init__(self) -> None:
        self._engine = None
        self._sqlite = sqlite3.connect(":memory:", check_same_thread=False)
        self._sqlite.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_sqlite()
        if S.use_external:
            try:
                from sqlalchemy import create_engine
                url = (f"mysql+pymysql://{S.mysql_user}:{S.mysql_password}"
                       f"@{S.mysql_host}:{S.mysql_port}/{S.mysql_db}")
                self._engine = create_engine(url, pool_pre_ping=True)
            except Exception:
                self._engine = None

    def _init_sqlite(self) -> None:
        self._sqlite.executescript("""
          CREATE TABLE sessions(thread_id TEXT PRIMARY KEY, user_id TEXT, tenant_id TEXT, state_json TEXT);
          CREATE TABLE idempotency(idem_key TEXT PRIMARY KEY, result_json TEXT, ttl_seconds INT);
          CREATE TABLE approvals(id TEXT PRIMARY KEY, tool TEXT, status TEXT, args_json TEXT);
          CREATE TABLE checkpoints(task_id TEXT PRIMARY KEY, status TEXT, completed_json TEXT);
          CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT, user_id TEXT, tool TEXT, status TEXT);
          CREATE TABLE traces(trace_id TEXT PRIMARY KEY, root_span_json TEXT);
        """)
        self._sqlite.commit()

    @property
    def active_backend(self) -> str:
        return "mysql" if self._engine else "sqlite-fallback"

    @staticmethod
    def _to_named(sql: str, params: tuple) -> tuple[str, dict[str, Any]]:
        """sqlite 的 ? 占位符 → SQLAlchemy 命名参数 :p0..:pN。"""
        parts = sql.split("?")
        if len(parts) - 1 != len(params):
            raise ValueError("占位符数量与参数数量不一致")
        out = parts[0] + "".join(f":p{i}" + parts[i + 1] for i in range(len(params)))
        return out, {f"p{i}": v for i, v in enumerate(params)}

    def _run_remote(self, sql: str, params: tuple, fetch: bool) -> Any:
        from sqlalchemy import text
        stmt, bound = self._to_named(sql, params)
        with self._engine.begin() as conn:      # type: ignore[union-attr]
            r = conn.execute(text(stmt), bound)
            if fetch:
                return [dict(row._mapping) for row in r.fetchall()]
            return r.rowcount

    def execute(self, sql: str, params: tuple = ()) -> int:
        if self._engine:
            try:
                return int(self._run_remote(sql, params, fetch=False))
            except Exception:
                pass                            # MySQL 不可用时落回 sqlite，保证链路可用
        with self._lock:
            cur = self._sqlite.execute(sql, params)
            self._sqlite.commit()
            return cur.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        if self._engine:
            try:
                return list(self._run_remote(sql, params, fetch=True))
            except Exception:
                pass
        with self._lock:
            return [dict(r) for r in self._sqlite.execute(sql, params).fetchall()]

    def stats(self) -> dict[str, Any]:
        if self._engine:
            try:
                rows = self.query("SELECT table_name FROM information_schema.tables "
                                  "WHERE table_schema = :p0", (S.mysql_db,))
                return {"backend": "mysql", "tables": [r.get("table_name", "") for r in rows]}
            except Exception:
                pass
        return {"backend": "sqlite-fallback", "mysql_engine_configured": self._engine is not None,
                "tables": [r[0] for r in self._sqlite.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]}


class KVStore:
    """Redis ↔ dict+TTL：会话状态、缓存、限流、幂等辅助。"""
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()
        self._redis = None
        if S.use_external:
            try:
                import redis
                self._redis = redis.Redis(host=S.redis_host, port=S.redis_port, socket_timeout=1)
                self._redis.ping()
            except Exception:
                self._redis = None

    @property
    def active_backend(self) -> str:
        return "redis" if self._redis else "memory-fallback"

    def set(self, k: str, v: Any, ttl: int = 300) -> None:
        if self._redis:
            try:
                self._redis.setex(k, ttl, json.dumps(v, ensure_ascii=False, default=str))
                return
            except Exception:
                self._redis = None             # 运行中掉线 → 切内存，别把请求打挂
        with self._lock:
            self._data[k] = (v, time.time() + ttl)

    def get(self, k: str) -> Any | None:
        if self._redis:
            try:
                raw = self._redis.get(k)
                return json.loads(raw) if raw else None
            except Exception:
                self._redis = None
        with self._lock:
            item = self._data.get(k)
            if not item:
                return None
            if time.time() > item[1]:
                del self._data[k]
                return None
            return item[0]

    def incr(self, k: str) -> int:
        v = int(self.get(k) or 0) + 1
        self.set(k, v, 60)
        return v

    def stats(self) -> dict[str, Any]:
        return {"backend": self.active_backend,
                "keys": len(self._data) if not self._redis else "redis-managed"}


class MessageBus:
    """RabbitMQ(pika) ↔ queue.Queue：长任务、审计、RAG 增量索引三类事件。"""
    TOPICS = ("task.#", "audit.#", "rag.#")

    def __init__(self) -> None:
        self._q: dict[str, queue.Queue] = {t: queue.Queue() for t in self.TOPICS}
        self._conn = None
        self._ch = None
        if S.use_external:
            try:
                import pika
                cred = pika.PlainCredentials(S.rabbit_user, S.rabbit_password)
                self._conn = pika.BlockingConnection(
                    pika.ConnectionParameters(S.rabbit_host, credentials=cred))
                self._ch = self._conn.channel()
                self._ch.exchange_declare("agent.topic", "topic", durable=True)
            except Exception:
                self._conn = None

    @property
    def active_backend(self) -> str:
        return "rabbitmq" if self._conn else "inproc-fallback"

    def publish(self, routing_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._conn:
            try:
                import pika
                self._ch.basic_publish("agent.topic", routing_key,
                                       json.dumps(payload, ensure_ascii=False).encode(),
                                       properties=pika.BasicProperties(delivery_mode=2))
            except Exception:
                self._conn = None              # 掉线后退到进程内队列，保证审计不丢
        topic = next((t for t in self.TOPICS if routing_key.startswith(t[:-1])), "task.#")
        self._q[topic].put({"routing_key": routing_key, **payload})
        return {"published": True, "routing_key": routing_key, "backend": self.active_backend}

    def consume(self, topic: str = "task.#", limit: int = 10) -> list[dict[str, Any]]:
        q = self._q.get(topic, queue.Queue())
        return [q.get_nowait() for _ in range(limit) if not q.empty()]

    def stats(self) -> dict[str, Any]:
        return {"backend": self.active_backend,
                "pending": {t: q.qsize() for t, q in self._q.items()}}


VECTOR = MilvusAdapter()
DB = RelationalStore()
KV = KVStore()
BUS = MessageBus()


def infra_report() -> dict[str, Any]:
    return {"milvus": VECTOR.stats(), "mysql": DB.stats(),
            "redis": KV.stats(), "rabbitmq": BUS.stats(),
            "external_enabled": S.use_external,
            "note": "未安装/未配置外部服务时全部降级到进程内实现，接口不变"}
