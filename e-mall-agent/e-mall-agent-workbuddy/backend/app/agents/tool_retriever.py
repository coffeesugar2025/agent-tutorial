"""Tool RAG：工具的动态语义检索。

对工具的 name/description 建轻量向量索引（复用 ``HashEmbeddings``），检索时
把向量余弦相似度与词面覆盖率融合打分。可与 RBAC 组合使用：先做权限过滤，
再做语义裁剪，确保不会把无权限工具透露给模型。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings

from ..rag.embeddings import HashEmbeddings, tokenize


@dataclass
class ToolHit:
    """一次工具检索命中项。"""

    tool: Any
    name: str
    score: float


class ToolRetriever:
    """基于工具名与描述的轻量检索器。

    Args:
        tools: 可被检索的工具对象（需有 ``name`` 与 ``description`` 属性）。
        embeddings: 可注入的嵌入实现；缺省使用确定性的 ``HashEmbeddings``。
    """

    def __init__(self, tools: Sequence[Any], embeddings: Embeddings | None = None) -> None:
        self.tools = list(tools)
        self.embeddings = embeddings or HashEmbeddings()
        self._names = [str(getattr(t, "name", "") or getattr(t, "__name__", "")) for t in self.tools]
        self._docs = [f"{name} {name} {self._description(t)}" for name, t in zip(self._names, self.tools)]
        self._vectors = self.embeddings.embed_documents(self._docs)
        self._tokens = [set(tokenize(doc)) for doc in self._docs]

    @staticmethod
    def _description(tool: Any) -> str:
        """读取工具描述，兼容 langchain BaseTool 与普通函数。"""
        return str(getattr(tool, "description", None)
                   or getattr(tool, "__doc__", "") or "").strip()

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        return sum(a * b for a, b in zip(left, right))

    def _score(self, query: str, index: int, query_vector: Sequence[float]) -> float:
        """融合向量余弦与词面覆盖率，避免短文本哈希碰撞导致的误排序。"""
        cosine = self._cosine(query_vector, self._vectors[index])
        q_tokens = set(tokenize(query))
        lexical = (len(q_tokens & self._tokens[index]) / len(q_tokens)) if q_tokens else 0.0
        return 0.65 * cosine + 0.35 * lexical

    def rank(self, query: str) -> list[ToolHit]:
        """按相关度从高到低返回全部工具命中项。"""
        vector = self.embeddings.embed_query(query)
        hits = [
            ToolHit(tool=tool, name=name, score=self._score(query, i, vector))
            for i, (tool, name) in enumerate(zip(self.tools, self._names))
        ]
        return sorted(hits, key=lambda hit: (-hit.score, hit.name))

    def search_with_scores(self, query: str, top_k: int = 5) -> list[ToolHit]:
        """返回带分数的 top_k 命中项。"""
        if top_k < 1:
            raise ValueError("top_k 必须 >= 1")
        return self.rank(query)[:top_k]

    def search(self, query: str, top_k: int = 5) -> list[Any]:
        """返回最相关的 top_k 个工具对象。"""
        return [hit.tool for hit in self.search_with_scores(query, top_k)]

    def filtered_search(self, query: str, user: Any, top_k: int = 5) -> list[Any]:
        """先按 RBAC 过滤出有权限的工具，再做语义检索（不修改工具本身）。

        权限过滤复用 ``app.security.rbac.filter_tools``，语义裁剪只发生在
        已授权集合内部，从而避免工具 RAG 成为越权信息泄露通道。
        """
        from ..security.rbac import filter_tools  # 局部导入，避免包级副作用

        allowed = filter_tools(self.tools, user)
        allowed_ids = {id(tool) for tool in allowed}
        hits = [hit for hit in self.rank(query) if id(hit.tool) in allowed_ids]
        return [hit.tool for hit in hits[:top_k]]
