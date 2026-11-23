"""多级降级链。

按注册顺序依次尝试若干处理函数，前一级失败（抛异常或返回哨兵值）后
自动切换到下一级，并记录每一级的尝试结果与最终生效的来源。
"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


class FallbackExhausted(RuntimeError):
    """所有降级级别均失败时抛出。"""


@dataclass
class FallbackAttempt:
    """单个降级级别的尝试记录。

    Attributes:
        name: 级别名称。
        ok: 该级别是否成功。
        value: 成功时的返回值。
        error: 失败时的异常信息。
    """

    name: str
    ok: bool
    value: Any = None
    error: str = ""


@dataclass
class FallbackResult:
    """降级链执行结果。

    Attributes:
        value: 最终返回值。
        source: 最终生效的级别名称。
        attempts: 按执行顺序排列的各级尝试记录。
        degraded: 是否发生了降级（即非第一级生效）。
    """

    value: Any
    source: str
    attempts: list[FallbackAttempt] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """是否由备用级别（非第一级）提供了结果。"""
        first = self.attempts[0] if self.attempts else None
        return bool(first and first.name != self.source)


class FallbackChain:
    """多级降级执行器。

    每一级是一个 ``(name, fn)`` 二元组。执行时按顺序调用，若某级抛出异常
    或返回 ``FallbackChain.SKIP`` 哨兵值，则继续下一级；全部失败时抛出
    ``FallbackExhausted``。同步与异步函数均可注册。
    """

    SKIP = object()
    """哨兵值：表示该级别主动放弃，交给下一级处理。"""

    def __init__(self, steps: list[tuple[str, Callable[..., Any]]]) -> None:
        if not steps:
            raise ValueError("FallbackChain 至少需要一个级别")
        self.steps: list[tuple[str, Callable[..., Any]]] = list(steps)

    def add(self, name: str, fn: Callable[..., Any]) -> FallbackChain:
        """在链尾追加一个降级级别并返回自身，便于链式调用。"""
        self.steps.append((name, fn))
        return self

    async def run(self, *args: Any, **kwargs: Any) -> FallbackResult:
        """依次尝试各级别，返回首个成功结果。

        Args:
            *args: 透传给每一级函数的位置参数。
            **kwargs: 透传给每一级函数的关键字参数。

        Returns:
            ``FallbackResult``，含最终值与完整的尝试记录。

        Raises:
            FallbackExhausted: 所有级别均失败。
        """
        attempts: list[FallbackAttempt] = []
        for name, fn in self.steps:
            try:
                value = fn(*args, **kwargs)
                if inspect.isawaitable(value):
                    value = await value
                if value is self.SKIP:
                    attempts.append(FallbackAttempt(name, ok=False, error="主动跳过"))
                    continue
                attempts.append(FallbackAttempt(name, ok=True, value=value))
                return FallbackResult(value=value, source=name, attempts=attempts)
            except Exception as exc:  # noqa: BLE001 - 降级需吞掉任意异常
                attempts.append(FallbackAttempt(name, ok=False, error=str(exc)))
        raise FallbackExhausted(
            "所有降级级别均失败: " + ", ".join(a.name for a in attempts)
        )
