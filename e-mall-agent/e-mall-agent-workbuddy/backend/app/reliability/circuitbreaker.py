"""三态熔断器：closed / open / half_open。

基于失败率阈值与冷却时间做状态迁移；``clock`` 可注入以便确定性测试冷却，
``call`` 支持同步与异步可调用对象。
"""
from __future__ import annotations

import asyncio
import inspect
import time
from enum import Enum
from typing import Any, Callable


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """熔断处于 open / 半开占用时拒绝调用。"""


class CircuitBreaker:
    """失败率超阈值后熔断，冷却后进入半开做恢复探测。"""

    def __init__(
        self,
        failure_threshold: float = 0.5,
        min_calls: int = 5,
        cooldown_seconds: float = 30.0,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not 0 < failure_threshold <= 1:
            raise ValueError("failure_threshold 必须在 (0, 1] 之间")
        if min_calls < 1:
            raise ValueError("min_calls 必须 >= 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds 不能为负")
        self.failure_threshold = failure_threshold
        self.min_calls = min_calls
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock or time.monotonic
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._total = 0
        self._failures = 0
        self._half_calls = 0

    @property
    def state(self) -> CircuitState:
        """当前状态；open 且冷却结束会惰性迁移到 half_open。"""
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if self._clock() - self._opened_at >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_calls = 0
        return self._state

    @property
    def failure_rate(self) -> float:
        return self._failures / self._total if self._total else 0.0

    def reset(self) -> None:
        """手动复位到 closed 并清空计数。"""
        self._state = CircuitState.CLOSED
        self._opened_at = None
        self._total = 0
        self._failures = 0
        self._half_calls = 0

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()

    def _before_call(self) -> None:
        current = self.state
        if current is CircuitState.OPEN:
            raise CircuitOpenError("熔断器处于 open 状态，调用被拒绝")
        if current is CircuitState.HALF_OPEN:
            if self._half_calls >= 1:
                raise CircuitOpenError("半开状态已有探测请求，请稍后重试")
            self._half_calls += 1

    def _on_success(self) -> None:
        self._total = 0
        self._failures = 0
        if self.state is CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._opened_at = None
            self._half_calls = 0

    def _on_failure(self) -> None:
        self._total += 1
        self._failures += 1
        if self.state is CircuitState.HALF_OPEN:
            self._trip()
        elif self._total >= self.min_calls and self.failure_rate >= self.failure_threshold:
            self._trip()

    async def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """在熔断器保护下执行同步 / 异步函数。"""
        self._before_call()
        try:
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result


__all__ = ["CircuitBreaker", "CircuitOpenError", "CircuitState"]
