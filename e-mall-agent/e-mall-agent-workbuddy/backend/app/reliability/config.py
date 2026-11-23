"""可靠性策略的一站式装配。

``ResilienceConfig`` 把幂等、超时、重试、降级与终止条件组装成单层包装，
对外只暴露一个异步 ``run`` 方法。
"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .idempotency import IdempotencyGuard
from .retry import RetryPolicy
from .stop import StopConditions, StopDecision, StopState
from .timeout import TimeoutPolicy


class StopRequestedError(RuntimeError):
    """终止条件命中且未提供降级方案时抛出。"""


@dataclass
class ResilienceConfig:
    """可靠性策略容器。

    Attributes:
        retry: 重试策略，可选。
        timeout: 超时策略，可选。
        idempotency: 幂等守卫，可选。
        stop: 终止条件，可选。
    """

    retry: RetryPolicy | None = None
    timeout: TimeoutPolicy | None = None
    idempotency: IdempotencyGuard | None = None
    stop: StopConditions | None = None

    def check_stop(
        self, state: StopState | None = None, **kwargs: Any
    ) -> StopDecision:
        """单独检查终止条件；未配置时返回不停。"""
        if self.stop is None:
            return StopDecision(False, "")
        return self.stop.check(state, **kwargs)

    @staticmethod
    async def _resolve_fallback(fallback: Any, reason: str) -> Any:
        """解析降级值：可调用则执行（支持异步），否则直接作为常量返回。"""
        if callable(fallback):
            value = fallback()
            if inspect.isawaitable(value):
                value = await value
            return value
        return fallback

    async def run(
        self,
        key: str,
        fn: Callable[[], Any],
        *,
        fallback: Any = None,
        stop_state: StopState | None = None,
    ) -> Any:
        """按 幂等 -> 终止条件 -> 超时 -> 重试 -> 降级 的顺序执行 ``fn``。

        Args:
            key: 幂等键。
            fn: 无参可调用对象，同步/异步均可。
            fallback: 执行失败或终止时使用的降级值或可调用降级函数。
            stop_state: 终止条件的运行时快照。

        Returns:
            成功结果、缓存结果或降级结果。

        Raises:
            StopRequestedError: 终止条件命中且没有降级方案。
            Exception: 执行失败且没有降级方案时抛出原始异常。
        """
        async def guarded() -> Any:
            if self.stop is not None and stop_state is not None:
                decision = self.stop.check(stop_state)
                if decision.should_stop:
                    if fallback is None:
                        raise StopRequestedError(decision.reason)
                    return await self._resolve_fallback(fallback, decision.reason)

            async def invoke() -> Any:
                if self.timeout is not None:
                    return await self.timeout.call(fn)
                value = fn()
                if inspect.isawaitable(value):
                    value = await value
                return value

            try:
                if self.retry is not None:
                    return await self.retry.call(invoke)
                return await invoke()
            except Exception as exc:  # noqa: BLE001 - 统一进入降级链
                if fallback is None:
                    raise
                return await self._resolve_fallback(fallback, str(exc))

        if self.idempotency is not None:
            return await self.idempotency.execute(key, guarded)
        return await guarded()
