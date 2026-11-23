"""模型路由：任务分类 → 模型档位（fast / strong）+ 成本表 + 升级策略。

成本表统一以"**分 / 百万 token**"为单位（人民币），便于 ``cost_cents`` 直接落库。
价格会随供应商调整，这里给出的是对齐官网量级的近似值，生产可通过配置覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config import settings

FAST = "fast"
STRONG = "strong"


class TaskClass(str, Enum):
    """任务分类（决定档位）。"""

    ROUTE = "route"          # supervisor 意图路由
    CHAT = "chat"            # 主对话
    TOOL_REASON = "tool"     # 工具调用推理
    RERANK = "rerank"        # 检索重排
    JUDGE = "judge"          # 评测裁判
    SUMMARY = "summary"      # 会话摘要
    TEXT2SQL = "text2sql"    # 运营取数
    COMPLEX = "complex"      # 复杂分析

    @property
    def tier(self) -> str:
        return FAST if self in _FAST_TASKS else STRONG


_FAST_TASKS = {
    TaskClass.ROUTE,
    TaskClass.RERANK,
    TaskClass.JUDGE,
    TaskClass.SUMMARY,
}


@dataclass(frozen=True)
class ModelChoice:
    """一次模型选择结果。"""

    provider: str
    model: str
    tier: str = STRONG
    price_in: float = 0.0
    price_out: float = 0.0
    price_cached: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


# 单位：分 / 百万 token（输入、输出、命中缓存输入）
MODEL_PRICES: dict[str, tuple[float, float, float]] = {
    "deepseek-chat": (190.0, 790.0, 40.0),
    "deepseek-reasoner": (400.0, 1600.0, 100.0),
    "qwen-max": (240.0, 960.0, 60.0),
    "qwen-turbo": (30.0, 60.0, 10.0),
    "qwen-plus": (80.0, 200.0, 20.0),
    "gpt-4o-mini": (110.0, 430.0, 55.0),
    "gpt-4o": (1800.0, 7200.0, 900.0),
    "qwen2.5:7b": (0.0, 0.0, 0.0),
    "mock-chat": (0.0, 0.0, 0.0),
}

# 未登记模型的兜底单价（避免成本统计断档）
_DEFAULT_PRICE = (200.0, 800.0, 50.0)


def provider_models(provider: str, fast: bool) -> str:
    """按供应商返回档位默认模型名。"""
    provider = provider.lower()
    if provider == "deepseek":
        return "deepseek-chat"
    if provider == "qwen":
        return settings.qwen_fast_model if fast else settings.qwen_model
    if provider == "openai":
        return settings.openai_model
    if provider == "ollama":
        return settings.ollama_model
    if provider == "mock":
        return "mock-chat"
    return settings.deepseek_model


def price_of(model: str) -> tuple[float, float, float]:
    return MODEL_PRICES.get(model, _DEFAULT_PRICE)


def make_choice(provider: str, tier: str, model: str | None = None) -> ModelChoice:
    resolved = model or provider_models(provider, fast=(tier == FAST))
    price_in, price_out, price_cached = price_of(resolved)
    return ModelChoice(
        provider=provider.lower(),
        model=resolved,
        tier=tier,
        price_in=price_in,
        price_out=price_out,
        price_cached=price_cached,
    )


def route(task: TaskClass, agent_type: str | None = None) -> ModelChoice:
    """主路由：按任务分类选档位；运营分析统一走 strong。"""
    tier = task.tier
    if agent_type == "OPS" and task in (TaskClass.TEXT2SQL, TaskClass.COMPLEX):
        tier = STRONG
    return make_choice(settings.effective_primary, tier)


def escalate(choice: ModelChoice) -> ModelChoice:
    """fast → strong 升级（同一供应商内的更强模型）。"""
    if choice.tier == STRONG:
        return choice
    return make_choice(choice.provider, STRONG)


def candidates(task: TaskClass, agent_type: str | None = None) -> list[ModelChoice]:
    """候选链：主供应商 fast → 主供应商 strong → 各兜底供应商。

    顺序遵循"同模型档位优先、供应商兜底在后"，兼顾成本与可用性。
    """
    primary = route(task, agent_type)
    chain: list[ModelChoice] = [primary]
    if primary.tier == FAST:
        chain.append(escalate(primary))
    for provider in settings.fallback_providers:
        if provider == primary.provider:
            continue
        chain.append(make_choice(provider, primary.tier))
    # 去重（provider + model）
    seen: set[tuple[str, str]] = set()
    unique: list[ModelChoice] = []
    for choice in chain:
        key = (choice.provider, choice.model)
        if key in seen:
            continue
        seen.add(key)
        unique.append(choice)
    return unique


def model_matrix() -> list[dict[str, object]]:
    """``/admin/models`` 用的模型清单（健康状态由 fallback 模块补充）。"""
    rows: list[dict[str, object]] = []
    chain = candidates(TaskClass.CHAT)
    for index, choice in enumerate(chain):
        rows.append(
            {
                "provider": choice.provider,
                "model": choice.model,
                "role": "primary" if index == 0 else "fallback",
                "tier": choice.tier,
                "priceIn": choice.price_in,
                "priceOut": choice.price_out,
            }
        )
    return rows


__all__ = [
    "FAST",
    "MODEL_PRICES",
    "STRONG",
    "ModelChoice",
    "TaskClass",
    "candidates",
    "escalate",
    "make_choice",
    "model_matrix",
    "price_of",
    "provider_models",
    "route",
]
