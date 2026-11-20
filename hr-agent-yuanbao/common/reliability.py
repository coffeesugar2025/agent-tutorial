"""生产级可靠性零件：重试 / 超时 / 幂等 / 熔断 / 降级 / 终止条件。

这一层是「跑 Demo」和「上生产干活」的分水岭。第 13 章会逐个演示。
"""
from __future__ import annotations

import functools
import random
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------- 重试（指数退避 + 抖动） ----------
def retry(fn: Callable[[], Any], *, times: int = 3, base_delay: float = 0.05,
          retry_on: tuple[type[BaseException], ...] = (Exception,),
          on_retry: Callable[[int, BaseException], None] | None = None) -> Any:
    last: BaseException | None = None
    for attempt in range(1, times + 1):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if attempt == times:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            if on_retry:
                on_retry(attempt, exc)
            time.sleep(delay)
    raise RuntimeError(f"重试 {times} 次后仍失败：{last}") from last


# ---------- 超时 ----------
def with_timeout(fn: Callable[[], Any], seconds: float) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=seconds)
        except FuturesTimeout as exc:
            future.cancel()
            raise TimeoutError(f"工具执行超过 {seconds}s") from exc


# ---------- 幂等 ----------
class IdempotencyStore:
    """同一个业务键只执行一次，重复请求直接返回首次结果。

    生产要点：把 key 存在数据库并加 UNIQUE 索引（本工程的 leave_requests.idem_key
    就是真实版），而不是内存 dict —— 进程重启后内存会丢。
    """
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def execute(self, key: str, fn: Callable[[], Any]) -> tuple[Any, bool]:
        if key in self._store:
            return self._store[key], False       # (结果, 是否真正执行)
        result = fn()
        self._store[key] = result
        return result, True


# ---------- 熔断 ----------
class CircuitBreaker:
    """连续失败到阈值后短暂开路，避免把故障放大到整个系统。"""
    def __init__(self, threshold: int = 3, reset_after: float = 2.0):
        self.threshold, self.reset_after = threshold, reset_after
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at and time.time() - self.opened_at > self.reset_after:
            self.opened_at, self.failures = None, 0   # half-open -> closed
            return False
        return self.opened_at is not None

    def call(self, fn: Callable[[], Any]) -> Any:
        if self.is_open:
            raise RuntimeError("熔断器已开路，快速失败")
        try:
            out = fn()
            self.failures = 0
            return out
        except Exception:
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = time.time()
            raise


@contextmanager
def degraded(fallback: Callable[[], Any], *, label: str = "降级"):
    """把异常转成可控的降级结果，而不是让整个 Agent 崩掉。"""
    try:
        yield None
    except Exception as exc:
        raise DegradedResult(fallback(), str(exc), label) from exc


class DegradedResult(Exception):
    def __init__(self, value: Any, reason: str, label: str):
        super().__init__(f"{label}: {reason}")
        self.value, self.reason, self.label = value, reason, label


# ---------- 终止条件 ----------
@dataclass
class BudgetGuard:
    """Agent Loop 必须有"刹车"：步数、时间、Token 三个维度任一超标就停。"""
    max_steps: int = 8
    max_seconds: float = 30.0
    token_budget: int = 3000
    steps: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.time)
    reasons: list[str] = field(default_factory=list)

    def tick(self, tokens: int = 0) -> None:
        self.steps += 1
        self.tokens += tokens

    def should_stop(self) -> str | None:
        if self.steps >= self.max_steps:
            return f"达到最大步数 {self.max_steps}"
        if time.time() - self.started > self.max_seconds:
            return f"超过时间预算 {self.max_seconds}s"
        if self.tokens >= self.token_budget:
            return f"超过 Token 预算 {self.token_budget}"
        return None

    def snapshot(self) -> dict:
        return {"steps": self.steps, "tokens": self.tokens,
                "elapsed_s": round(time.time() - self.started, 3),
                "max_steps": self.max_steps, "token_budget": self.token_budget}
