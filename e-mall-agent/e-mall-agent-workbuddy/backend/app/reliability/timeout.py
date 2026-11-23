"""超时控制策略。

基于 ``asyncio.wait_for`` 为异步调用加上时间上限，超时后可返回降级值
或抛出自定义的 ``AgentTimeoutError``。
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class AgentTimeoutError(TimeoutError):
    """异步操作超出给定时限时抛出的自定义异常。"""


class TimeoutPolicy:
    """异步超时控制。

    Args:
        timeout: 时限秒数，必须为正数。
        fallback_value: 超时时的降级返回值；仅在 ``raise_on_timeout=False`` 时使用。
        raise_on_timeout: 超时时抛出异常还是返回降级值。
    """

    def __init__(
        self,
        timeout: float,
        fallback_value: Any = None,
        raise_on_timeout: bool = True,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须 > 0")
        self.timeout = timeout
        self.fallback_value = fallback_value
        self.raise_on_timeout = raise_on_timeout

    async def call(
        self, fn: Callable[..., T | Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T | Any:
        """在时限内执行可调用对象。

        同步函数会被直接调用（同步阻塞无法被 wait_for 中断），异步函数
        通过 ``asyncio.wait_for`` 受控。超时行为由构造参数决定。

        Args:
            fn: 待执行的可调用对象。
            *args: 位置参数。
            **kwargs: 关键字参数。

        Returns:
            正常返回 ``fn`` 的结果；超时且配置降级时返回 ``fallback_value``。

        Raises:
            AgentTimeoutError: 超时且 ``raise_on_timeout=True``。
        """
        result = fn(*args, **kwargs)
        if not inspect.isawaitable(result):
            return result
        try:
            return await asyncio.wait_for(result, timeout=self.timeout)
        except TimeoutError as exc:
            if self.raise_on_timeout:
                raise AgentTimeoutError(
                    f"操作超过 {self.timeout} 秒未完成"
                ) from exc
            return self.fallback_value
