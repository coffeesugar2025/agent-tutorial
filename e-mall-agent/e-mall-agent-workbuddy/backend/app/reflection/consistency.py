"""Self-Consistency 自洽性投票。

对同一问题多次采样，取多数表决的答案作为最终结果；支持传入现成样本列表，
也支持注入采样函数并按次数采样。平票时按确定性规则（得分高、字母序）裁决。
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field


class ConsistencyResult(BaseModel):
    """投票结果与置信度。

    Attributes:
        answer: 胜出的答案。
        votes: 规范化答案 -> 票数。
        total: 参与投票的样本总数。
        confidence: 胜出答案得票占比。
        tied: 是否出现平票。
    """

    answer: str
    votes: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    confidence: float = 0.0
    tied: bool = False


def _normalize(text: Any) -> str:
    """去首尾空白并压缩内部空白，避免同义格式被算作不同答案。"""
    return " ".join(str(text).split())


def majority_vote(samples: Sequence[Any]) -> ConsistencyResult:
    """对样本做多数表决。

    平票裁决按 ``(-票数, 答案文本)`` 排序，保证纯本地、确定性可断言。
    """
    normalized = [_normalize(s) for s in samples if _normalize(s)]
    if not normalized:
        raise ValueError("self-consistency 至少需要一条非空样本")
    counts = Counter(normalized)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    winner, top = ordered[0]
    tied = len(ordered) > 1 and ordered[1][1] == top
    return ConsistencyResult(
        answer=winner,
        votes=dict(counts),
        total=len(normalized),
        confidence=top / len(normalized),
        tied=tied,
    )


class SelfConsistency:
    """可复用的一致性投票器，采样函数可注入。"""

    def __init__(self, sampler: Callable[[str], Any] | None = None) -> None:
        self.sampler = sampler

    def vote(self, samples: Sequence[Any]) -> ConsistencyResult:
        """对给定样本列表投票。"""
        return majority_vote(samples)

    def sample_and_vote(self, task: str, n: int = 5) -> ConsistencyResult:
        """调用注入的采样函数 n 次后投票；采样函数需事先提供。"""
        if self.sampler is None:
            raise ValueError("sample_and_vote 需要先注入 sampler")
        if n < 1:
            raise ValueError("n 必须 >= 1")
        return majority_vote([self.sampler(task) for _ in range(n)])
