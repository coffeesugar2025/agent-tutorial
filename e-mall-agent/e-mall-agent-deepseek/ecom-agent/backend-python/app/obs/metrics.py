"""Prometheus 指标（前缀 ``ecom_agent_``）。

``prometheus_client`` 未安装时自动降级为 No-Op 实现，保证离线环境与单元测试
可运行；此时 ``/metrics`` 返回说明性文本而非崩溃。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-16] 可观测与调试
# 职责：Prometheus 指标（前缀 ``ecom_agent_``）
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于运行环境
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except Exception:  # noqa: BLE001 - 任何导入异常都降级
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


class _NoopMetric:
    """未安装 prometheus_client 时的空实现。"""

    def labels(self, *args: Any, **kwargs: Any) -> _NoopMetric:
        return self

    def inc(self, amount: float = 1) -> None:
        return None

    def dec(self, amount: float = 1) -> None:
        return None

    def observe(self, value: float) -> None:
        return None

    def set(self, value: float) -> None:
        return None


def _counter(name: str, doc: str, labels: tuple[str, ...]) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    return Counter(f"ecom_agent_{name}", doc, labels)


def _gauge(name: str, doc: str, labels: tuple[str, ...] = ()) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    return Gauge(f"ecom_agent_{name}", doc, labels)


def _histogram(name: str, doc: str, labels: tuple[str, ...], buckets: tuple[float, ...]) -> Any:
    if not PROMETHEUS_AVAILABLE:
        return _NoopMetric()
    return Histogram(f"ecom_agent_{name}", doc, labels, buckets=buckets)


# --- 契约要求的 7 个核心指标 -------------------------------------------------
REQUESTS_TOTAL = _counter("requests", "HTTP 请求数", ("method", "path", "status"))
LLM_CALLS_TOTAL = _counter("llm_calls", "LLM 调用次数", ("provider", "model", "status"))
LLM_TOKENS_TOTAL = _counter("llm_tokens", "LLM token 数", ("provider", "model", "kind"))
LLM_COST_CENTS_TOTAL = _counter("llm_cost_cents", "LLM 成本（分）", ("provider", "model"))
TOOL_CALLS_TOTAL = _counter("tool_calls", "工具调用次数", ("tool", "risk", "status"))
AGENT_STEP_SECONDS = _histogram(
    "agent_step_seconds", "Agent 单步耗时", ("agent_type",), (0.05, 0.2, 0.5, 1, 2, 5, 10, 30, 60)
)
APPROVAL_PENDING = _gauge("approval_pending", "待审批任务数")

# --- 扩展指标 ---------------------------------------------------------------
AGENT_TASKS_TOTAL = _counter("agent_tasks", "Agent 任务结束原因", ("reason",))
DEGRADATIONS_TOTAL = _counter("degradations", "降级事件", ("component", "reason"))
RAG_QUERY_SECONDS = _histogram(
    "rag_query_seconds", "检索耗时", ("mode",), (0.01, 0.05, 0.1, 0.3, 1, 3, 10)
)
HTTP_LATENCY_SECONDS = _histogram(
    "http_latency_seconds", "HTTP 耗时", ("method", "path"), (0.05, 0.1, 0.3, 1, 3, 10, 30, 120)
)


def record_request(method: str, path: str, status: int, latency_seconds: float) -> None:
    REQUESTS_TOTAL.labels(method=method, path=path, status=str(status)).inc()
    HTTP_LATENCY_SECONDS.labels(method=method, path=path).observe(latency_seconds)


def record_llm_call(provider: str, model: str, status: str, latency_seconds: float) -> None:
    LLM_CALLS_TOTAL.labels(provider=provider, model=model, status=status).inc()


def record_tokens(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    if prompt_tokens:
        LLM_TOKENS_TOTAL.labels(provider=provider, model=model, kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS_TOTAL.labels(provider=provider, model=model, kind="completion").inc(completion_tokens)


def record_cost(provider: str, model: str, cost_cents: int) -> None:
    if cost_cents:
        LLM_COST_CENTS_TOTAL.labels(provider=provider, model=model).inc(cost_cents)


def record_tool_call(tool: str, risk: str, status: str) -> None:
    TOOL_CALLS_TOTAL.labels(tool=tool, risk=risk, status=status).inc()


def record_agent_step(agent_type: str, latency_seconds: float) -> None:
    AGENT_STEP_SECONDS.labels(agent_type=agent_type).observe(latency_seconds)


def record_termination(reason: str) -> None:
    AGENT_TASKS_TOTAL.labels(reason=reason).inc()


def record_degradation(component: str, reason: str) -> None:
    DEGRADATIONS_TOTAL.labels(component=component, reason=reason).inc()
    logger.warning("降级事件 component=%s reason=%s", component, reason)


def record_rag_query(mode: str, latency_seconds: float) -> None:
    RAG_QUERY_SECONDS.labels(mode=mode).observe(latency_seconds)


def set_approval_pending(count: int) -> None:
    APPROVAL_PENDING.set(count)


def metrics_text() -> tuple[bytes, str]:
    """返回 ``/metrics`` 的响应体与 Content-Type。"""
    if not PROMETHEUS_AVAILABLE:
        body = (
            "# prometheus_client 未安装，指标已降级为 No-Op。\n"
            "# 安装依赖后重启即可暴露 ecom_agent_* 指标。\n"
            "ecom_agent_metrics_degraded 1\n"
        )
        return body.encode("utf-8"), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


__all__ = [
    "AGENT_STEP_SECONDS",
    "APPROVAL_PENDING",
    "PROMETHEUS_AVAILABLE",
    "metrics_text",
    "record_agent_step",
    "record_cost",
    "record_degradation",
    "record_llm_call",
    "record_rag_query",
    "record_request",
    "record_termination",
    "record_tokens",
    "record_tool_call",
    "set_approval_pending",
]
