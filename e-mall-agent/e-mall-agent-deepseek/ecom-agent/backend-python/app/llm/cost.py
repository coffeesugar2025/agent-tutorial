"""Token 计费与 ``llm_call`` 落库。

* 计费以模型返回的 usage 为准；Mock / 无 usage 时用 :mod:`app.common.tokens` 估算；
* ``cached_tokens`` 单独计价（命中缓存的输入按 ``price_cached`` 折算）；
* 聚合接口供 ``/admin/overview``、``/admin/costs`` 使用：按模型、按供应商、按天。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.common.tokens import estimate_messages_tokens, estimate_tokens
from app.infra import models_obs
from app.infra.db import session_scope
from app.llm.router import ModelChoice
from app.obs.metrics import record_cost, record_tokens

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """一次调用的 token 统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cache_hit_rate(self) -> float:
        if not self.prompt_tokens:
            return 0.0
        return min(self.cached_tokens / self.prompt_tokens, 1.0)

    def to_dict(self) -> dict[str, int]:
        return {
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "cachedTokens": self.cached_tokens,
        }

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )


@dataclass
class CostSummary:
    total_cents: int = 0
    calls: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    by_provider: dict[str, int] = field(default_factory=dict)
    daily: dict[str, int] = field(default_factory=dict)


def _dig(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_usage(
    message: Any = None,
    messages: list[Any] | None = None,
    text: str | None = None,
) -> TokenUsage:
    """优先读模型 usage，缺失时估算。"""
    usage = TokenUsage()
    usage_metadata = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}

    prompt = usage_metadata.get("input_tokens") or _dig(response_metadata, "token_usage", "prompt_tokens")
    completion = usage_metadata.get("output_tokens") or _dig(
        response_metadata, "token_usage", "completion_tokens"
    )
    cached = (
        _dig(usage_metadata, "input_token_details", "cache_read")
        or _dig(response_metadata, "token_usage", "prompt_tokens_details", "cached_tokens")
        or _dig(response_metadata, "token_usage", "prompt_cache_hit_tokens")
        or 0
    )

    if prompt:
        usage.prompt_tokens = int(prompt)
    elif messages:
        usage.prompt_tokens = estimate_messages_tokens(messages)
    if completion:
        usage.completion_tokens = int(completion)
    elif text:
        usage.completion_tokens = estimate_tokens(text)
    usage.cached_tokens = min(int(cached or 0), usage.prompt_tokens)
    return usage


def compute_cost_cents(choice: ModelChoice, usage: TokenUsage) -> int:
    """按 "分/百万 token" 单价折算，向上取整到分。"""
    cached = max(usage.cached_tokens, 0)
    fresh_prompt = max(usage.prompt_tokens - cached, 0)
    raw = (
        fresh_prompt / 1_000_000 * choice.price_in
        + cached / 1_000_000 * choice.price_cached
        + usage.completion_tokens / 1_000_000 * choice.price_out
    )
    if raw <= 0:
        return 0
    # 有真实消耗时至少记 1 分，避免截图/报表出现 0 成本
    return max(int(raw + 0.999), 1)


def record_llm_call(
    choice: ModelChoice,
    usage: TokenUsage,
    cost_cents: int,
    latency_ms: int,
    status: str = "OK",
    trace_id: str | None = None,
    span_id: str | None = None,
) -> int:
    """写 ``llm_call`` 并更新 Prometheus 指标，返回主键（失败返回 0）。"""
    record_tokens(choice.provider, choice.model, usage.prompt_tokens, usage.completion_tokens)
    record_cost(choice.provider, choice.model, cost_cents)
    try:
        with session_scope() as db:
            row = models_obs.LlmCall(
                trace_id=trace_id,
                span_id=span_id,
                provider=choice.provider,
                model=choice.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cached_tokens=usage.cached_tokens,
                cost_cents=cost_cents,
                latency_ms=latency_ms,
                status=status,
            )
            db.add(row)
            db.flush()
            return int(row.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("写 llm_call 失败: %s", exc)
        return 0


def summarize_costs(days: int = 7) -> CostSummary:
    """按时间窗聚合成本（供 /admin/costs 与 /admin/overview）。"""
    from app.common.timeutil import day_str, days_ago

    summary = CostSummary()
    try:
        with session_scope() as db:
            start = days_ago(days)
            rows = (
                db.query(
                    models_obs.LlmCall.model,
                    models_obs.LlmCall.provider,
                    func.count(models_obs.LlmCall.id),
                    func.coalesce(func.sum(models_obs.LlmCall.cost_cents), 0),
                    func.coalesce(func.sum(models_obs.LlmCall.prompt_tokens), 0),
                    func.coalesce(func.sum(models_obs.LlmCall.completion_tokens), 0),
                    func.coalesce(func.sum(models_obs.LlmCall.cached_tokens), 0),
                )
                .filter(models_obs.LlmCall.created_at >= start)
                .group_by(models_obs.LlmCall.model, models_obs.LlmCall.provider)
                .all()
            )
            for model, provider, calls, cost, prompt, completion, cached in rows:
                summary.calls += int(calls)
                summary.total_cents += int(cost)
                summary.by_model[str(model)] = {
                    "calls": int(calls),
                    "costCents": int(cost),
                    "promptTokens": int(prompt),
                    "completionTokens": int(completion),
                    "cachedTokens": int(cached),
                }
                summary.by_provider[str(provider)] = summary.by_provider.get(str(provider), 0) + int(cost)

            daily_rows = (
                db.query(func.date(models_obs.LlmCall.created_at), func.coalesce(func.sum(models_obs.LlmCall.cost_cents), 0))
                .filter(models_obs.LlmCall.created_at >= start)
                .group_by(func.date(models_obs.LlmCall.created_at))
                .all()
            )
            for day, cost in daily_rows:
                key = day_str(datetime.fromisoformat(str(day))) if not isinstance(day, datetime) else day_str(day)
                summary.daily[key] = int(cost)
    except Exception as exc:  # noqa: BLE001
        logger.warning("聚合成本失败: %s", exc)
    return summary


def cost_per_success_cents(days: int = 7) -> float:
    """每"成功任务"成本：总成本 / SUCCESS trace 数（无成功任务时为 0）。"""
    from app.common.timeutil import days_ago

    try:
        with session_scope() as db:
            start = days_ago(days)
            total_cost = int(
                db.query(func.coalesce(func.sum(models_obs.AgentTrace.total_cost_cents), 0))
                .filter(models_obs.AgentTrace.created_at >= start)
                .scalar()
                or 0
            )
            success = int(
                db.query(func.count(models_obs.AgentTrace.id))
                .filter(
                    models_obs.AgentTrace.created_at >= start,
                    models_obs.AgentTrace.status == "SUCCESS",
                )
                .scalar()
                or 0
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("统计每成功任务成本失败: %s", exc)
        return 0.0
    if success <= 0:
        return 0.0
    return round(total_cost / success, 2)


def model_call_stats(days: int = 7) -> dict[str, dict[str, float]]:
    """模型维度的调用次数与平均延迟（/admin/models 用）。"""
    from app.common.timeutil import days_ago

    stats: dict[str, dict[str, float]] = {}
    try:
        with session_scope() as db:
            rows = (
                db.query(
                    models_obs.LlmCall.model,
                    func.count(models_obs.LlmCall.id),
                    func.coalesce(func.avg(models_obs.LlmCall.latency_ms), 0),
                )
                .filter(models_obs.LlmCall.created_at >= days_ago(days))
                .group_by(models_obs.LlmCall.model)
                .all()
            )
            for model, calls, avg_latency in rows:
                stats[str(model)] = {"calls": int(calls), "avgLatencyMs": float(avg_latency or 0)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("统计模型调用失败: %s", exc)
    return stats


__all__ = [
    "CostSummary",
    "TokenUsage",
    "compute_cost_cents",
    "cost_per_success_cents",
    "extract_usage",
    "model_call_stats",
    "record_llm_call",
    "summarize_costs",
]
