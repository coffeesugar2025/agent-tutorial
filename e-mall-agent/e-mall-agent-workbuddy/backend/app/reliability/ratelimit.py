"""令牌桶限流：同步尝试 + 异步等待，支持注入时钟与等待函数。"""
from __future__ import annotations

import asyncio
import time
from typing import Callable


class TokenBucket:
    """按固定速率补充令牌的有界令牌桶。

    ``clock`` 与 ``sleeper`` 可注入，便于测试中不依赖真实时间：
    注入的 ``sleeper`` 每被调用一次即推进假时钟即可驱动 ``acquire`` 循环。
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], asyncio.Future] | Callable[[float], object] | None = None,
    ) -> None:
        if capacity <= 0 or refill_rate <= 0:
            raise ValueError("capacity 与 refill_rate 必须为正")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep
        self._tokens = self.capacity
        self._updated = self._clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._updated = now

    @property
    def available(self) -> float:
        """当前可用令牌数。"""
        self._refill()
        return self._tokens

    def reset(self) -> None:
        """恢复满桶状态。"""
        self._tokens = self.capacity
        self._updated = self._clock()

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """非阻塞获取；令牌不足或请求量超过容量时返回 False。"""
        if tokens <= 0:
            return True
        if tokens > self.capacity:
            return False
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    async def acquire(self, tokens: float = 1.0,
                      timeout: float | None = None) -> bool:
        """异步等待直到拿到令牌；超时返回 False，成功返回 True。"""
        if tokens <= 0:
            return True
        if tokens > self.capacity:
            return False
        deadline = None if timeout is None else self._clock() + timeout
        while True:
            if self.try_acquire(tokens):
                return True
            now = self._clock()
            if deadline is not None and now >= deadline:
                return False
            wait = max(0.0, tokens - self._tokens) / self.refill_rate
            if deadline is not None:
                wait = min(wait, deadline - now)
            await self._sleeper(max(wait, 0.001))


__all__ = ["TokenBucket"]
