"""精确 Token 预算：可选 tiktoken + 本地中英文分词估算回退。

未安装 tiktoken 时使用确定性估算：中文字符按 1 token/字，拉丁词按
每 4 字符 1 token（不足按 1 计），标点单独计。接口与 ``TokenCounter``
协议一致，可在测试中直接注入替身。不修改 ``context/engine.py``。
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_OR_PUNCT = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


class BudgetSplit(BaseModel):
    """按 token 上限切分后的结果。"""

    kept: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    used: int = 0
    limit: int = 0


@runtime_checkable
class TokenCounter(Protocol):
    """Token 计数器的最小协议。"""

    def count(self, text: str) -> int:
        """统计文本的 token 数。"""
        ...

    def budget_split(self, texts: Sequence[str], limit: int) -> BudgetSplit:
        """按上限切分文本序列。"""
        ...


class EnhancedTokenCounter:
    """本地增强实现：优先 tiktoken，缺失时回退到中英文分别估算。"""

    def __init__(self, encoding_name: str = "cl100k_base", *, use_tiktoken: bool = True) -> None:
        self.encoding_name = encoding_name
        self._encoding: Any = None
        if use_tiktoken:
            try:
                import tiktoken  # type: ignore[import-not-found]

                self._encoding = tiktoken.get_encoding(encoding_name)
            except (ImportError, KeyError, ValueError):
                self._encoding = None

    @property
    def uses_tiktoken(self) -> bool:
        """当前是否真正启用了 tiktoken。"""
        return self._encoding is not None

    def count(self, text: str) -> int:
        """统计 token 数；空文本返回 0。"""
        text = text or ""
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text))

        cjk = len(_CJK.findall(text))
        rest = _CJK.sub(" ", text)
        latin = sum(
            max(1, round(len(token) / 4))
            for token in _LATIN_OR_PUNCT.findall(rest)
        )
        return cjk + latin

    def budget_split(self, texts: Sequence[str], limit: int) -> BudgetSplit:
        """按原始顺序贪心保留能放进预算的文本，其余记入 dropped。"""
        if limit < 0:
            raise ValueError("limit 必须 >= 0")
        kept: list[str] = []
        dropped: list[str] = []
        used = 0
        for text in texts:
            cost = self.count(text)
            if used + cost <= limit:
                kept.append(text)
                used += cost
            else:
                dropped.append(text)
        return BudgetSplit(kept=kept, dropped=dropped, used=used, limit=limit)


# 便于按实现名导入的别名
LocalTokenCounter = EnhancedTokenCounter
