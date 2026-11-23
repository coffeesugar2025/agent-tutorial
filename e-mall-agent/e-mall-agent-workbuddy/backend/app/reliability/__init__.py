"""可靠性能力包：重试、超时、降级、幂等、终止条件与一站式装配。

所有组件均可独立使用，也可通过 ``ResilienceConfig`` 组合成一层包装。
"""
from __future__ import annotations

from .config import ResilienceConfig, StopRequestedError
from .fallback import (
    FallbackAttempt,
    FallbackChain,
    FallbackExhausted,
    FallbackResult,
)
from .idempotency import (
    IdempotencyGuard,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)
from .retry import RetryPolicy
from .stop import StopConditions, StopDecision, StopState
from .timeout import AgentTimeoutError, TimeoutPolicy

__all__ = [
    "AgentTimeoutError",
    "FallbackAttempt",
    "FallbackChain",
    "FallbackExhausted",
    "FallbackResult",
    "IdempotencyGuard",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "ResilienceConfig",
    "RetryPolicy",
    "StopConditions",
    "StopDecision",
    "StopRequestedError",
    "StopState",
    "TimeoutPolicy",
]
