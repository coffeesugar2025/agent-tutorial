"""生产级可靠性：错误恢复 / 重试 / 幂等 / 超时 / 降级 / 终止条件 / 熔断。

原有项目已有：ModelRetryMiddleware、调用次数上限、MCP 三级降级、recursion_limit。
本模块把这些能力做成可独立复用、可单测的策略对象，并补齐幂等、超时、熔断、
重复动作检测与显式终止条件。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# ---------------------------------------------------------------- 重试
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_factor: float = 0.05
    jitter: bool = True
    retry_on: tuple[type[BaseException], ...] = (Exception,)
    # 总纲 5.1：可重试错误分类。True=命中的 validation/auth/quota 直接终止；
    # unknown 类别仍按原 retry_on 语义重试，保证既有调用方行为不变。
    classify_errors: bool = True

    def _should_retry(self, exc: BaseException) -> bool:
        if not self.classify_errors:
            return True
        from app.hardening.errors import classify
        c = classify(exc)
        return c.retryable or c.kind == "unknown"

    def delay(self, attempt: int) -> float:
        base = self.backoff_factor * (2 ** max(0, attempt - 1))
        return base + (random.random() * base * 0.2 if self.jitter else 0.0)

    def run_sync(self, fn: Callable[[], Any]) -> tuple[Any, list[str]]:
        errors: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                return fn(), errors
            except self.retry_on as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                if not self._should_retry(exc):
                    raise
                if attempt == self.max_attempts:
                    raise
                time.sleep(self.delay(attempt))
        raise RuntimeError("unreachable")

    async def arun(self, fn: Callable[[], Awaitable[Any]]) -> tuple[Any, list[str]]:
        errors: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await fn(), errors
            except self.retry_on as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                if not self._should_retry(exc):
                    raise
                if attempt == self.max_attempts:
                    raise
                await asyncio.sleep(self.delay(attempt))
        raise RuntimeError("unreachable")


# ---------------------------------------------------------------- 超时
class TimeoutError_(TimeoutError):
    pass


async def with_timeout(coro: Awaitable[Any], seconds: float,
                       fallback: Any = None) -> tuple[bool, Any, float]:
    """超时不抛断，返回 (ok, value, elapsed_ms)；fallback 为降级值。"""
    started = time.perf_counter()
    try:
        value = await asyncio.wait_for(coro, timeout=seconds)
        return True, value, int((time.perf_counter() - started) * 1000)
    except (asyncio.TimeoutError, TimeoutError):
        return False, fallback, int((time.perf_counter() - started) * 1000)


# ---------------------------------------------------------------- 幂等
@dataclass
class IdempotencyRecord:
    key: str
    result: Any
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 3600.0

    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds


class IdempotencyStore:
    """按 (operation, payload) 生成稳定 key，重复请求直接返回首次结果。"""

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._data: dict[str, IdempotencyRecord] = {}
        self._lock = threading.RLock()
        self.ttl = ttl_seconds

    @staticmethod
    def make_key(operation: str, payload: Any) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return operation + ":" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    def get(self, key: str) -> Any | None:
        with self._lock:
            rec = self._data.get(key)
            if rec and rec.expired():
                del self._data[key]
                return None
            return rec.result if rec else None

    def put(self, key: str, result: Any) -> None:
        with self._lock:
            self._data[key] = IdempotencyRecord(key, result, ttl_seconds=self.ttl)

    def execute(self, operation: str, payload: Any, fn: Callable[[], Any]) -> dict[str, Any]:
        key = self.make_key(operation, payload)
        cached = self.get(key)
        if cached is not None:
            return {"key": key, "replayed": True, "result": cached}
        result = fn()
        self.put(key, result)
        return {"key": key, "replayed": False, "result": result}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"size": len(self._data), "ttl_seconds": self.ttl}


# ---------------------------------------------------------------- 熔断 / 降级
class CircuitBreaker:
    """closed → open → half_open → closed，带失败阈值与恢复窗口。"""

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 2.0) -> None:
        self.threshold = failure_threshold
        self.recovery = recovery_seconds
        self.failures = 0
        self.state = "closed"
        self.opened_at = 0.0
        self._lock = threading.RLock()

    def allow(self) -> bool:
        with self._lock:
            if self.state == "open" and time.time() - self.opened_at >= self.recovery:
                self.state = "half_open"
            return self.state != "open"

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self.state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.state = "open"
                self.opened_at = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state, "failures": self.failures,
                "threshold": self.threshold, "recovery_seconds": self.recovery}


def degrade_chain(primary: Callable[[], Any],
                  fallbacks: list[tuple[str, Callable[[], Any]]]) -> dict[str, Any]:
    """依次尝试主路径与降级路径，如实返回最终生效的来源。"""
    attempts: list[dict[str, Any]] = []
    for name, fn in [("primary", primary), *fallbacks]:
        try:
            result = fn()
            attempts.append({"source": name, "status": "ok"})
            return {"result": result, "source": name, "degraded": name != "primary",
                    "attempts": attempts}
        except Exception as exc:
            attempts.append({"source": name, "status": "error",
                             "error": f"{type(exc).__name__}: {exc}"})
    return {"result": None, "source": "none", "degraded": True, "attempts": attempts}


# ---------------------------------------------------------------- 终止条件
@dataclass
class TerminationPolicy:
    max_steps: int = 12
    max_seconds: float = 30.0
    repeated_call_limit: int = 2
    allow_stop_reasons: tuple[str, ...] = (
        "completed", "max_steps", "max_seconds", "repeated_action", "tool_failure", "user_abort",
    )

    def __post_init__(self) -> None:
        self.started = time.perf_counter()
        self.steps = 0
        self._calls: dict[str, int] = {}

    def observe(self, action: str | None = None) -> str | None:
        """每步调用一次；返回非 None 表示应立即终止，并给出原因。"""
        self.steps += 1
        if action:
            self._calls[action] = self._calls.get(action, 0) + 1
            if self._calls[action] > self.repeated_call_limit:
                return "repeated_action"
        if self.steps > self.max_steps:
            return "max_steps"
        if time.perf_counter() - self.started > self.max_seconds:
            return "max_seconds"
        return None

    def snapshot(self) -> dict[str, Any]:
        return {"steps": self.steps, "max_steps": self.max_steps,
                "max_seconds": self.max_seconds, "call_counts": dict(self._calls),
                "elapsed_ms": int((time.perf_counter() - self.started) * 1000)}


def reliability_report() -> dict[str, Any]:
    """给 /v2/capabilities 的能力自述。"""
    return {
        "retry": "RetryPolicy（指数退避 + jitter，同步/异步）",
        "timeout": "with_timeout（wait_for + 降级值，不抛断）",
        "idempotency": "IdempotencyStore（sha256 key + TTL + replay）",
        "circuit_breaker": "CircuitBreaker（closed/open/half_open）",
        "degradation": "degrade_chain（如实返回生效来源）",
        "termination": "TerminationPolicy（步数/耗时/重复动作/工具失败/用户中止）",
        "existing_in_v1": ["ModelRetryMiddleware", "ModelCallLimitMiddleware",
                           "ToolCallLimitMiddleware", "recursion_limit=24",
                           "MCP 三级降级 builtin→adapters→local"],
    }
