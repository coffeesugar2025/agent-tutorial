"""Embedding 四种实现：dashscope / openai / ollama / hash。

``hash`` 是本项目的离线方案：用"特征哈希 + 符号位 + L2 归一化"把词袋映射到固定维度，
同一文本永远得到同一向量，且语义相近（共享 token 多）的文本余弦相似度高。
它不具备真正的语义泛化能力，但足够支撑检索链路的单测、CI 与首次体验。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-12] 检索增强 RAG
# 职责：Embedding 四种实现：dashscope / openai / ollama / hash
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import hashlib
import logging
import math
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx

from app.config import settings
from app.rag.sparse import token_id, tokenize, term_weight

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """向量化失败（网络/鉴权/维度不匹配）。"""


class BaseEmbedding(ABC):
    """向量化接口。"""

    provider: str = "base"
    dim: int = 1024

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文档向量。"""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """单条查询向量。"""

    def health(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Hash（离线）
# ---------------------------------------------------------------------------
class HashEmbedding(BaseEmbedding):
    """确定性哈希向量：无需联网、无需模型文件。"""

    provider = "hash"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = max(int(dim), 64)

    @staticmethod
    def _sign(token: str) -> float:
        digest = hashlib.blake2b(("s:" + token).encode("utf-8"), digest_size=2).digest()
        return -1.0 if digest[0] & 1 else 1.0

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        if not text:
            return vector
        tokens = tokenize(text)
        if not tokens:
            return vector
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, tf in counts.items():
            index = token_id(token) % self.dim
            weight = term_weight(token, tf) * self._sign(token)
            vector[index] += weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [round(value / norm, 6) for value in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# ---------------------------------------------------------------------------
# OpenAI 兼容（dashscope / openai / 自建网关）
# ---------------------------------------------------------------------------
class OpenAICompatibleEmbedding(BaseEmbedding):
    """调用 ``{base_url}/embeddings`` 的通用实现（一次最多 10 条，兼容 DashScope 限制）。"""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        batch_size: int = 10,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise EmbeddingError(f"{provider} 未配置 API Key")
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.batch_size = max(batch_size, 1)
        self.timeout = timeout

    def _request(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, object] = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.provider == "dashscope":
            payload["dimensions"] = self.dim
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"{self.provider} embedding 调用失败: {exc}") from exc
        data = body.get("data") or []
        vectors = [item.get("embedding") or [] for item in data]
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise EmbeddingError(f"{self.provider} embedding 返回数量不匹配")
        if vectors and len(vectors[0]) != self.dim:
            logger.warning(
                "embedding 维度不一致: 配置 %s，实际 %s（以实际为准）", self.dim, len(vectors[0])
            )
            self.dim = len(vectors[0])
        return [[float(value) for value in vector] for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._request(texts[start : start + self.batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._request([text])[0]

    def health(self) -> bool:
        try:
            self.embed_query("health check")
            return True
        except EmbeddingError:
            return False


class OllamaEmbedding(BaseEmbedding):
    """Ollama 本地向量（``/api/embeddings``，逐条调用）。"""

    provider = "ollama"

    def __init__(self, base_url: str, model: str, dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim

    def _request(self, text: str) -> list[float]:
        try:
            response = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30.0,
            )
            response.raise_for_status()
            vector = response.json().get("embedding") or []
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"ollama embedding 调用失败: {exc}") from exc
        if not vector:
            raise EmbeddingError("ollama embedding 返回为空")
        self.dim = len(vector)
        return [float(value) for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._request(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._request(text)


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
# ──────── [CAP-12] 检索增强 RAG ────────
#   本处：向量化工厂（含离线 hash 兜底）
#   域约束：任一环节失败必须降级并标记 degraded，不允许静默返回空结果
def build_embedding(provider: str | None = None) -> BaseEmbedding:
    """按 ``EMBEDDING_PROVIDER`` 构建；失败自动降级到 hash 并记日志。"""
    resolved = (provider or settings.embedding_provider or "hash").lower()
    try:
        if resolved == "hash":
            return HashEmbedding(settings.embedding_dim)
        if resolved == "dashscope":
            return OpenAICompatibleEmbedding(
                provider="dashscope",
                base_url=settings.dashscope_base_url,
                api_key=settings.dashscope_api_key,
                model=settings.embedding_model,
                dim=settings.embedding_dim,
            )
        if resolved == "openai":
            return OpenAICompatibleEmbedding(
                provider="openai",
                base_url=settings.openai_base_url,
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                dim=settings.embedding_dim,
            )
        if resolved == "ollama":
            return OllamaEmbedding(
                base_url=settings.ollama_base_url,
                model=settings.embedding_model,
                dim=settings.embedding_dim,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding 供应商 %s 初始化失败，降级 hash: %s", resolved, exc)
        return HashEmbedding(settings.embedding_dim)
    logger.warning("未知 EMBEDDING_PROVIDER=%s，降级 hash", resolved)
    return HashEmbedding(settings.embedding_dim)


@lru_cache(maxsize=1)
def get_embedding() -> BaseEmbedding:
    """进程级单例。"""
    return build_embedding()


def reset_embedding() -> None:
    """测试用：清空单例（切换 provider/维度后生效）。"""
    get_embedding.cache_clear()


__all__ = [
    "BaseEmbedding",
    "EmbeddingError",
    "HashEmbedding",
    "OllamaEmbedding",
    "OpenAICompatibleEmbedding",
    "build_embedding",
    "get_embedding",
    "reset_embedding",
]
