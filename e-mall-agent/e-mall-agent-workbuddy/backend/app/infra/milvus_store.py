"""Milvus 向量库适配器：未配置时回退到 InMemoryVectorStore + HashEmbeddings。

pymilvus 只在真实调用时导入；回退路径完全复用项目现有的离线检索实现，
因此不需要 API key、不需要网络，结果可复现。
"""
from __future__ import annotations

import importlib.util
import json
from typing import Any

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore

from ..rag.embeddings import HashEmbeddings
from .settings import InfraSettings

_COLLECTION = "ecom_knowledge"
_DIM = 128


class MilvusVectorStore:
    """Milvus / 内存双模向量库。"""

    def __init__(self, url: str | None = None, token: str | None = None,
                 settings: InfraSettings | None = None) -> None:
        cfg = settings or InfraSettings.from_env()
        self.url = url if url is not None else cfg.milvus_url
        self.token = token if token is not None else cfg.milvus_token
        self._embeddings = HashEmbeddings()
        self._fallback = InMemoryVectorStore(self._embeddings)
        self._client: Any = None

    @property
    def configured(self) -> bool:
        """是否已显式配置 Milvus URL。"""
        return bool(self.url)

    @staticmethod
    def _driver_available() -> bool:
        return importlib.util.find_spec("pymilvus") is not None

    def _get_client(self) -> Any:
        """懒加载 MilvusClient；不可用时返回 None 触发内存回退。"""
        if not self.configured or not self._driver_available():
            return None
        if self._client is None:
            try:
                from pymilvus import MilvusClient  # type: ignore

                self._client = MilvusClient(uri=self.url, token=self.token or None)
            except Exception:
                return None
        return self._client

    @staticmethod
    def _ensure_collection(client: Any) -> None:
        """按 texts/metadata/vector 结构创建集合（若不存在）。"""
        if client.has_collection(_COLLECTION):
            return
        from pymilvus import CollectionSchema, DataType, FieldSchema  # type: ignore

        schema = CollectionSchema([
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=_DIM),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=8192),
        ])
        client.create_collection(collection_name=_COLLECTION, schema=schema)

    def add_texts(self, texts: list[str],
                  metadatas: list[dict[str, Any]] | None = None) -> list[str]:
        """写入文本并始终同步内存回退库，返回文档 id 列表。"""
        texts = list(texts)
        metadatas = metadatas or [{} for _ in texts]
        ids = self._fallback.add_texts(texts, metadatas=metadatas)
        client = self._get_client()
        if client is not None:
            try:
                self._ensure_collection(client)
                vectors = self._embeddings.embed_documents(texts)
                rows = [{
                    "vector": vector,
                    "text": text,
                    "metadata": json.dumps(meta or {}, ensure_ascii=False),
                } for text, vector, meta in zip(texts, vectors, metadatas)]
                client.insert(collection_name=_COLLECTION, data=rows)
            except Exception:
                pass  # 远端写入失败不影响本地回退结果
        return ids

    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        """相似度检索；远端不可用或失败时回退本地向量库。"""
        client = self._get_client()
        if client is not None:
            try:
                if client.has_collection(_COLLECTION):
                    hits = client.search(
                        collection_name=_COLLECTION,
                        data=[self._embeddings.embed_query(query)],
                        limit=k,
                        output_fields=["text", "metadata"],
                    )
                    documents: list[Document] = []
                    for result in hits:
                        for hit in result:
                            entity = hit.get("entity", {})
                            try:
                                meta = json.loads(entity.get("metadata") or "{}")
                            except (TypeError, ValueError):
                                meta = {}
                            documents.append(Document(
                                page_content=entity.get("text", ""),
                                metadata=meta if isinstance(meta, dict) else {}))
                    if documents:
                        return documents[:k]
            except Exception:
                pass
        return self._fallback.similarity_search(query, k=k)

    def status(self) -> dict[str, Any]:
        """组件状态（不建立网络连接）。"""
        active = self._get_client() is not None
        if not self.configured:
            detail = "not_configured: ECOM_MILVUS_URL 未配置，回退到 InMemoryVectorStore + HashEmbeddings"
        elif not self._driver_available():
            detail = "not_configured: 缺少 pymilvus 驱动，回退到 InMemoryVectorStore + HashEmbeddings"
        elif not active:
            detail = "Milvus URL 无效，回退到 InMemoryVectorStore + HashEmbeddings"
        else:
            detail = "Milvus 驱动可用，使用 Milvus 后端"
        return {
            "configured": self.configured,
            "active": active,
            "backend": "milvus" if active else "memory",
            "detail": detail,
        }
