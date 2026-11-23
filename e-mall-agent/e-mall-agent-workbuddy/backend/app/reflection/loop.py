"""Reflexion 反思与自纠错循环。

流程：执行器产出答案 -> Critic 打分 -> 未达标则带反馈修订再执行，直到达标、
达到最大迭代次数或质量连续停滞。执行器与 Critic 均可注入，因此无需真实
LLM 或网络即可确定性测试；同时支持同步与异步可调用对象。
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .models import Critique, ReflectionResult, ReflectionStep

Executor = Callable[[str, str | None], Any]
CriticFn = Callable[[str, str], Any]


def _as_critique(value: Any) -> Critique:
    """把 Critic 返回值规范化为 ``Critique``（支持 dict / 数值 / 元组）。"""
    if isinstance(value, Critique):
        return value
    if isinstance(value, dict):
        return Critique(**value)
    if isinstance(value, (int, float)):
        return Critique(score=float(value))
    if isinstance(value, tuple) and len(value) == 2:
        return Critique(score=float(value[0]), feedback=str(value[1]))
    raise TypeError("critic 必须返回 Critique / dict / 数值 / (score, feedback)")


class ReflexionLoop:
    """可注入 Critic 的反思循环。

    Args:
        executor: ``(task, feedback) -> answer``。首次 ``feedback=None``；修订轮
            传入上一轮反馈，便于同一函数实现「修订再执行」。
        critic: ``(task, answer) -> Critique``（或其可转换形式）。
        max_iterations: 最大执行轮数，必须 >= 1。
        score_threshold: 达标分数线。
        patience: 连续多少轮评分未有提升后提前停止；<=0 表示关闭该停止条件。
    """

    def __init__(
        self,
        executor: Executor,
        critic: CriticFn,
        *,
        max_iterations: int = 3,
        score_threshold: float = 0.8,
        patience: int = 2,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations 必须 >= 1")
        self.executor = executor
        self.critic = critic
        self.max_iterations = max_iterations
        self.score_threshold = score_threshold
        self.patience = patience

    # ---------- 共享判定逻辑 ----------
    def _accept(self, critique: Critique) -> bool:
        return critique.is_accepted(self.score_threshold)

    def _stop_reason(
        self, critique: Critique, iteration: int, best_score: float, stale: int
    ) -> str | None:
        """返回终止原因；未触发停止条件时返回 None。"""
        if self._accept(critique):
            return "答案达标"
        if iteration >= self.max_iterations:
            return f"达到最大迭代次数 {self.max_iterations}"
        if self.patience > 0 and stale >= self.patience:
            return f"连续 {stale} 轮评分未提升，提前停止（最佳 {best_score:.2f}）"
        return None

    def _finish(
        self, trace: list[ReflectionStep], reason: str
    ) -> ReflectionResult:
        return ReflectionResult(
            answer=trace[-1].answer if trace else "",
            iterations_used=len(trace),
            scores=[step.critique.score for step in trace],
            trace=list(trace),
            terminated_reason=reason,
            metadata={
                "max_iterations": self.max_iterations,
                "score_threshold": self.score_threshold,
                "best_score": max((s.critique.score for s in trace), default=0.0),
            },
        )

    # ---------- 同步 API ----------
    def run(self, task: str) -> ReflectionResult:
        """同步执行反思循环。若注入了异步可调用对象，请改用 ``arun``。"""
        trace: list[ReflectionStep] = []
        feedback: str | None = None
        best_score = -1.0
        stale = 0

        for iteration in range(1, self.max_iterations + 1):
            answer = self.executor(task, feedback)
            if inspect.isawaitable(answer):
                raise TypeError("检测到异步 executor，请改用 await arun(task)")
            answer = str(answer)
            critique = _as_critique(self.critic(task, answer))
            revised = feedback is not None
            trace.append(ReflectionStep(iteration=iteration, answer=answer,
                                        critique=critique, revised=revised))

            if critique.score > best_score + 1e-9:
                best_score = critique.score
                stale = 0
            else:
                stale += 1

            reason = self._stop_reason(critique, iteration, best_score, stale)
            if reason:
                return self._finish(trace, reason)
            feedback = critique.feedback or f"上一轮得分 {critique.score:.2f}，请改进。"

        return self._finish(trace, f"达到最大迭代次数 {self.max_iterations}")

    # ---------- 异步 API ----------
    @staticmethod
    async def _resolve(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    async def arun(self, task: str) -> ReflectionResult:
        """``run`` 的异步版本，自动 await 异步 executor / critic。"""
        trace: list[ReflectionStep] = []
        feedback: str | None = None
        best_score = -1.0
        stale = 0

        for iteration in range(1, self.max_iterations + 1):
            answer = str(await self._resolve(self.executor(task, feedback)))
            critique = _as_critique(await self._resolve(self.critic(task, answer)))
            revised = feedback is not None
            trace.append(ReflectionStep(iteration=iteration, answer=answer,
                                        critique=critique, revised=revised))

            if critique.score > best_score + 1e-9:
                best_score = critique.score
                stale = 0
            else:
                stale += 1

            reason = self._stop_reason(critique, iteration, best_score, stale)
            if reason:
                return self._finish(trace, reason)
            feedback = critique.feedback or f"上一轮得分 {critique.score:.2f}，请改进。"

        return self._finish(trace, f"达到最大迭代次数 {self.max_iterations}")
