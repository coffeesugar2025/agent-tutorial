"""反思循环中的结构化数据模型。

Critic 用一个 0~1 的质量分与自然语言反馈描述答案是否达标；ReflectionStep
记录单轮「执行 -> 评分」轨迹，ReflectionResult 汇总最终结果。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Critique(BaseModel):
    """Critic 对一次答案的评分与改进建议。

    Attributes:
        score: 0~1 的质量分，越高越好。
        feedback: 自然语言改进建议；达标时可为空。
        passed: 是否判定达标；未显式给出时按 ``score >= threshold`` 推断。
    """

    score: float
    feedback: str = ""
    passed: bool | None = None

    @field_validator("score")
    @classmethod
    def _clamp_score(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def is_accepted(self, threshold: float) -> bool:
        """按阈值判断是否达标（显式 passed 优先）。"""
        if self.passed is not None:
            return self.passed
        return self.score >= threshold


class ReflectionStep(BaseModel):
    """一轮反思轨迹：第几次迭代、产出的答案与对应评分。"""

    iteration: int
    answer: str
    critique: Critique
    revised: bool = False


class ReflectionResult(BaseModel):
    """ReflexionLoop 的最终结果。

    Attributes:
        answer: 最终采用的答案。
        iterations_used: 实际执行轮数。
        scores: 每轮评分，便于断言质量是否提升。
        trace: 每轮完整轨迹。
        terminated_reason: 终止原因（达标 / 达到最大迭代 / 质量停滞）。
    """

    answer: str
    iterations_used: int = 0
    scores: list[float] = Field(default_factory=list)
    trace: list[ReflectionStep] = Field(default_factory=list)
    terminated_reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
