"""指数退避重试策略。

提供可注入的异步重试包装器：指数退避 + 抖动，可选择可重试的异常类型，
并在每次重试时触发回调。零外部依赖，便于在离线环境中测试。
"""
from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

# 回调签名: (attempt, exception, delay) -> None，同步或异步均可
OnRetry = Callable[[int, BaseException, float], None | Awaitable[None]]


class RetryPolicy:
    """指数退避重试策略。

    对任意同步/异步可调用对象进行包装。第 n 次失败后的等待时间为
    ``min(base_delay * 2 ** (n - 1), max_delay) + jitter``，其中抖动为
    ``[0, jitter)`` 区间的随机数，默认关闭以保证离线测试确定性。

    Args:
        max_attempts: 最大尝试次数（含首次），至少为 1。
        base_delay: 首次失败后的基础等待秒数。
        max_delay: 单次等待的上限秒数。
        retryable_exceptions: 触发重试的异常类型元组。
        on_retry: 每次重试前调用的钩子，用于观测或记录。
        jitter: 叠加在退避时间上的最大随机抖动秒数。
        sleeper: 可注入的异步等待函数，便于测试中绕过真实 sleep。
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.01,
        max_delay: float = 1.0,
        retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
        on_retry: OnRetry | None = None,
        jitter: float = 0.0,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts 必须 >= 1")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retryable_exceptions = retryable_exceptions
        self.on_retry = on_retry
        self.jitter = jitter
        self._sleeper = sleeper or asyncio.sleep

    def delay_for(self, attempt: int) -> float:
        """计算第 ``attempt`` 次失败后的等待秒数。

        Args:
            attempt: 从 1 开始的失败序号。

        Returns:
            指数退避并叠加抖动后的等待秒数（不超过 max_delay + jitter）。
        """
        backoff = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        noise = random.uniform(0.0, self.jitter) if self.jitter > 0 else 0.0
        return backoff + noise

    async def call(
        self, fn: Callable[..., T | Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        """在重试策略下执行可调用对象。

        同步函数与异步函数均可传入；非可重试异常会立即向上抛出。
        所有尝试均失败时抛出最后一次异常。

        Args:
            fn: 待执行的可调用对象。
            *args: 位置参数。
            **kwargs: 关键字参数。

        Returns:
            ``fn`` 成功执行后的返回值。

        Raises:
            BaseException: 最后一次失败时抛出的原始异常。
        """
        last_error: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = fn(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except self.retryable_exceptions as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                delay = self.delay_for(attempt)
                if self.on_retry is not None:
                    hook = self.on_retry(attempt, exc, delay)
                    if inspect.isawaitable(hook):
                        await hook
                if delay > 0:
                    await self._sleeper(delay)
        assert last_error is not None
        raise last_error
