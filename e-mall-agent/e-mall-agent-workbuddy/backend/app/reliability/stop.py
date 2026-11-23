"""终止条件集合。

集中判断智能体循环是否应停止：最大步数、最大耗时、最大 token 预算、
连续无进展次数以及重复动作检测。判定结果以 ``StopDecision`` 返回。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StopDecision:
    """终止判定结果。

    Attributes:
        should_stop: 是否应终止。
        reason: 触发终止的条件描述，便于观测与调试。
    """

    should_stop: bool
    reason: str = ""


@dataclass
class StopState:
    """供终止条件检查的运行时快照。

    Attributes:
        steps: 已执行的步数。
        elapsed: 已耗时秒数。
        tokens: 已消耗的 token 数。
        no_progress: 连续无进展的轮次数。
        action: 当前动作标识，用于重复检测。
        history: 历史动作标识列表，用于重复检测。
    """

    steps: int = 0
    elapsed: float = 0.0
    tokens: int = 0
    no_progress: int = 0
    action: str | None = None
    history: list[str] = field(default_factory=list)


class StopConditions:
    """可组合的终止条件集合。

    所有条件均为可选；未设置的条件不参与判定。多个条件同时满足时，
    按构造时固定的优先级返回第一个命中的原因。

    Args:
        max_steps: 最大步数。
        max_duration: 最大耗时秒数。
        max_tokens: 最大 token 预算。
        max_no_progress: 允许的连续无进展轮次数。
        detect_repeat: 是否启用重复动作检测。
        repeat_threshold: 同一动作在历史中出现达到该次数即判定为重复。
    """

    def __init__(
        self,
        *,
        max_steps: int | None = None,
        max_duration: float | None = None,
        max_tokens: int | None = None,
        max_no_progress: int | None = None,
        detect_repeat: bool = False,
        repeat_threshold: int = 2,
    ) -> None:
        self.max_steps = max_steps
        self.max_duration = max_duration
        self.max_tokens = max_tokens
        self.max_no_progress = max_no_progress
        self.detect_repeat = detect_repeat
        self.repeat_threshold = repeat_threshold

    def check(
        self, state: StopState | None = None, **kwargs: Any
    ) -> StopDecision:
        """检查终止条件。

        Args:
            state: 运行时快照；为 None 时由 ``kwargs`` 构造。
            **kwargs: ``StopState`` 的字段，便于 ``check(steps=10)`` 直接调用。

        Returns:
            ``StopDecision``；未命中任何条件时 ``should_stop=False``。
        """
        snapshot = state if state is not None else StopState(**kwargs)
        if self.max_steps is not None and snapshot.steps >= self.max_steps:
            return StopDecision(True, f"达到最大步数 {self.max_steps}")
        if self.max_duration is not None and snapshot.elapsed >= self.max_duration:
            return StopDecision(True, f"达到最大耗时 {self.max_duration}s")
        if self.max_tokens is not None and snapshot.tokens >= self.max_tokens:
            return StopDecision(True, f"达到最大 token 预算 {self.max_tokens}")
        if (
            self.max_no_progress is not None
            and snapshot.no_progress >= self.max_no_progress
        ):
            return StopDecision(True, f"连续 {self.max_no_progress} 轮无进展")
        if self.detect_repeat and snapshot.action:
            count = snapshot.history.count(snapshot.action) + 1
            if count >= self.repeat_threshold:
                return StopDecision(True, f"检测到重复动作 {snapshot.action}")
        return StopDecision(False, "")
