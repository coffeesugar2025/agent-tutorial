"""多供应商 fallback 链 + 熔断器（CLOSED / OPEN / HALF_OPEN）。

调用策略：
1. 按 :func:`app.llm.router.candidates` 的顺序逐个尝试（主供应商 fast → strong → 兜底供应商）；
2. 每个供应商一个熔断器：连续失败 ``failure_threshold`` 次进入 OPEN，冷却
   ``recovery_seconds`` 后转 HALF_OPEN 放行一次探针，成功回 CLOSED；
3. 只要已经开始向客户端输出正文（delta），后续失败**不再换模型重放**，直接抛错，
   避免答案前后矛盾；
4. 每次成功调用都写 ``llm_call``（含 cached_tokens）并更新指标。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage

from app.common.errors import BizError, Codes
from app.common.timeutil import duration_ms
from app.common.tracecontext import get_trace_id
from app.config import settings
from app.infra.redis import redis_hub
from app.llm import providers
from app.llm.cost import TokenUsage, compute_cost_cents, extract_usage, record_llm_call
from app.llm.router import FAST, ModelChoice, TaskClass, candidates
from app.obs.metrics import record_llm_call as record_llm_metric

logger = logging.getLogger(__name__)


class LLMUnavailable(BizError):
    """所有候选模型都不可用（→ 50300，由 runtime 输出兜底话术）。"""

    def __init__(self, message: str = "模型服务暂不可用，已为你转接人工") -> None:
        super().__init__(Codes.DEGRADED, message)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


def _breaker_name(provider: str) -> str:
    return f"llm:{provider.lower()}"


class CircuitBreaker:
    """单供应商熔断器（进程内 + Redis 共享状态）。"""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
    ) -> None:
        self.name = name
        self.failure_threshold = max(failure_threshold, 1)
        self.recovery_seconds = recovery_seconds
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = 0.0
        self._half_open_inflight = False
        self._last_error = ""
        self._lock = threading.Lock()

    # --- 状态迁移 -----------------------------------------------------------
    def _maybe_half_open(self) -> None:
        if self._state == CircuitState.OPEN and (time.time() - self._opened_at) >= self.recovery_seconds:
            self._state = CircuitState.HALF_OPEN
            self._half_open_inflight = False
            logger.info("熔断器 %s → HALF_OPEN（放行探针）", self.name)
            self._publish()

    def _publish(self) -> None:
        try:
            redis_hub.set_state(
                "breaker",
                self.name,
                {"state": self._state.value, "openedAt": self._opened_at, "failures": self._failures},
                ttl=int(self.recovery_seconds * 2),
            )
        except Exception:  # noqa: BLE001
            pass

    def _remote_open(self) -> bool:
        try:
            remote = redis_hub.get_state("breaker", self.name)
        except Exception:  # noqa: BLE001
            return False
        if not isinstance(remote, dict):
            return False
        if remote.get("state") != CircuitState.OPEN.value:
            return False
        opened_at = float(remote.get("openedAt") or 0)
        return (time.time() - opened_at) < self.recovery_seconds

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def allow(self) -> bool:
        """是否放行本次调用。"""
        with self._lock:
            self._maybe_half_open()
            if self._state == CircuitState.OPEN:
                return False
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_inflight:
                    return False
                self._half_open_inflight = True
                return True
        return not self._remote_open()

    def record_success(self) -> None:
        with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info("熔断器 %s → CLOSED（探针成功）", self.name)
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._half_open_inflight = False
            self._opened_at = 0.0
            self._publish()

    def record_failure(self, error: str = "") -> None:
        with self._lock:
            self._failures += 1
            self._last_error = error[:200]
            self._half_open_inflight = False
            if self._state == CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()
                logger.warning(
                    "熔断器 %s → OPEN（failures=%s err=%s）", self.name, self._failures, self._last_error
                )
            self._publish()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._maybe_half_open()
            return {
                "provider": self.name.split(":", 1)[-1],
                "circuit": self._state.value,
                "failures": self._failures,
                "lastError": self._last_error or None,
            }

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = 0.0
            self._half_open_inflight = False
            self._last_error = ""


_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKERS_LOCK = threading.Lock()


def get_breaker(provider: str) -> CircuitBreaker:
    name = _breaker_name(provider)
    with _BREAKERS_LOCK:
        breaker = _BREAKERS.get(name)
        if breaker is None:
            breaker = CircuitBreaker(name)
            _BREAKERS[name] = breaker
        return breaker


def reset_breakers() -> None:
    """测试/运维用：重置全部熔断器。"""
    with _BREAKERS_LOCK:
        for breaker in _BREAKERS.values():
            breaker.reset()


def breaker_snapshot() -> dict[str, dict[str, Any]]:
    with _BREAKERS_LOCK:
        return {name: breaker.snapshot() for name, breaker in _BREAKERS.items()}


@dataclass
class LLMCallResult:
    """一次成功调用的完整结果。"""

    message: AIMessage
    text: str
    provider: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_cents: int = 0
    latency_ms: int = 0
    tier: str = ""
    finish_reason: str = "stop"
    attempts: int = 1

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return list(getattr(self.message, "tool_calls", None) or [])


class LLMClient:
    """统一的模型调用客户端（流式/非流式/结构化）。"""

    def __init__(self, recorder: Any = None) -> None:
        self.recorder = recorder

    # ------------------------------------------------------------------
    # 流式
    # ------------------------------------------------------------------
    async def astream(
        self,
        messages: list[BaseMessage],
        *,
        task: TaskClass = TaskClass.CHAT,
        tools: list[Any] | None = None,
        on_delta: Any = None,
        temperature: float | None = None,
    ) -> LLMCallResult:
        """按候选链流式调用；``on_delta(piece)`` 可为同步或异步回调。"""
        chain = candidates(task)
        emitted = {"any": False}
        errors: list[str] = []

        async def _delta(piece: str) -> None:
            emitted["any"] = True
            if on_delta is None:
                return
            result = on_delta(piece)
            if asyncio.iscoroutine(result):
                await result

        for attempt, choice in enumerate(chain, start=1):
            breaker = get_breaker(choice.provider)
            if not breaker.allow():
                logger.info("跳过熔断中的供应商 %s", choice.provider)
                continue
            started = time.perf_counter()
            try:
                message, text, usage = await self._stream_once(
                    choice, messages, tools=tools, on_delta=_delta, temperature=temperature
                )
            except Exception as exc:  # noqa: BLE001
                latency = duration_ms(started)
                breaker.record_failure(f"{type(exc).__name__}: {exc}")
                record_llm_metric(choice.provider, choice.model, "ERROR", latency / 1000)
                record_llm_call(choice, TokenUsage(), 0, latency, status="ERROR", trace_id=get_trace_id())
                errors.append(f"{choice.label}: {type(exc).__name__}: {exc}")
                logger.warning("模型调用失败 %s err=%s", choice.label, exc)
                if emitted["any"]:
                    raise LLMUnavailable("模型输出中断，请稍后重试") from exc
                continue

            latency = duration_ms(started)
            breaker.record_success()
            cost = compute_cost_cents(choice, usage)
            record_llm_metric(choice.provider, choice.model, "OK", latency / 1000)
            record_llm_call(
                choice, usage, cost, latency, status="OK", trace_id=get_trace_id()
            )
            return LLMCallResult(
                message=message,
                text=text,
                provider=choice.provider,
                model=choice.model,
                usage=usage,
                cost_cents=cost,
                latency_ms=latency,
                tier=choice.tier,
                finish_reason=str(getattr(message, "response_metadata", {}).get("finish_reason") or "stop"),
                attempts=attempt,
            )

        raise LLMUnavailable("；".join(errors)[-500:] or "没有可用的模型")

    async def _stream_once(
        self,
        choice: ModelChoice,
        messages: list[BaseMessage],
        *,
        tools: list[Any] | None,
        on_delta: Any,
        temperature: float | None,
    ) -> tuple[AIMessage, str, TokenUsage]:
        model = self._build(choice, tools, temperature)
        text_parts: list[str] = []
        final: Any = None
        async for event in model.astream_events(messages, version="v2"):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = (event.get("data") or {}).get("chunk")
                piece = getattr(chunk, "content", "") if chunk is not None else ""
                if isinstance(piece, str) and piece:
                    text_parts.append(piece)
                    await on_delta(piece)
            elif kind == "on_chat_model_end":
                final = (event.get("data") or {}).get("output")
        text = "".join(text_parts)
        message = self._normalize(final, text)
        usage = extract_usage(message, messages=messages, text=text)
        return message, text, usage

    @staticmethod
    def _normalize(final: Any, text: str) -> AIMessage:
        """把 on_chat_model_end 的输出统一成 AIMessage（便于落库与再用）。"""
        if final is None:
            return AIMessage(content=text)
        tool_calls = list(getattr(final, "tool_calls", None) or [])
        content = getattr(final, "content", text)
        if isinstance(content, list):
            content = "".join(str(part) for part in content)
        return AIMessage(
            content=content or text,
            tool_calls=tool_calls,
            usage_metadata=getattr(final, "usage_metadata", None),
            response_metadata=dict(getattr(final, "response_metadata", None) or {}),
        )

    def _build(self, choice: ModelChoice, tools: list[Any] | None, temperature: float | None) -> Any:
        model: BaseChatModel = providers.build_chat_model(
            choice.provider, choice.model, temperature=temperature
        )
        if tools:
            model = model.bind_tools(tools)  # type: ignore[assignment]
        return model

    # ------------------------------------------------------------------
    # 非流式
    # ------------------------------------------------------------------
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        *,
        task: TaskClass = TaskClass.CHAT,
        tools: list[Any] | None = None,
        temperature: float | None = None,
    ) -> LLMCallResult:
        result = await self.astream(
            messages, task=task, tools=tools, on_delta=None, temperature=temperature
        )
        return result

    # ------------------------------------------------------------------
    # 结构化输出
    # ------------------------------------------------------------------
    async def structured(
        self,
        messages: list[BaseMessage],
        schema: Any,
        *,
        task: TaskClass = TaskClass.ROUTE,
    ) -> Any:
        """结构化输出（路由/重排/裁判共用），失败自动降级到下一候选。"""
        chain = candidates(task)
        errors: list[str] = []
        for choice in chain:
            breaker = get_breaker(choice.provider)
            if not breaker.allow():
                continue
            started = time.perf_counter()
            try:
                model = providers.build_chat_model(choice.provider, choice.model)
                runnable = model.with_structured_output(schema)
                parsed = await runnable.ainvoke(messages)
            except Exception as exc:  # noqa: BLE001
                latency = duration_ms(started)
                breaker.record_failure(f"{type(exc).__name__}: {exc}")
                record_llm_metric(choice.provider, choice.model, "ERROR", latency / 1000)
                errors.append(f"{choice.label}: {exc}")
                continue
            latency = duration_ms(started)
            breaker.record_success()
            usage = TokenUsage(
                prompt_tokens=extract_usage(messages=messages).prompt_tokens,
                completion_tokens=0,
            )
            cost = compute_cost_cents(choice, usage)
            record_llm_metric(choice.provider, choice.model, "OK", latency / 1000)
            record_llm_call(choice, usage, cost, latency, status="OK", trace_id=get_trace_id())
            return parsed
        raise LLMUnavailable("；".join(errors)[-500:] or "结构化输出失败")


def health_snapshot(model_stats: dict[str, dict[str, float]] | None = None) -> list[dict[str, Any]]:
    """``/admin/models`` 数据：路由候选 × 熔断状态 × 近期调用统计。"""
    from app.llm.router import model_matrix

    stats = model_stats or {}
    rows: list[dict[str, Any]] = []
    for item in model_matrix():
        provider = str(item["provider"])
        breaker = get_breaker(provider).snapshot()
        stat = stats.get(str(item["model"]), {})
        rows.append(
            {
                "provider": provider,
                "model": item["model"],
                "role": item["role"],
                "healthy": breaker["circuit"] != CircuitState.OPEN.value,
                "circuit": breaker["circuit"],
                "avgLatencyMs": int(stat.get("avgLatencyMs", 0)),
                "calls": int(stat.get("calls", 0)),
                "tier": item.get("tier", FAST if item["role"] != "primary" else "strong"),
            }
        )
    return rows


__all__ = [
    "LLMCallResult",
    "LLMClient",
    "LLMUnavailable",
    "CircuitBreaker",
    "CircuitState",
    "breaker_snapshot",
    "get_breaker",
    "health_snapshot",
    "reset_breakers",
    "settings",
]
