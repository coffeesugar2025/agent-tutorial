"""推理模型配置与 Test-time Compute 参数生成。

推理模型（o1/o3/R1/QwQ 等）用 ``reasoning_effort`` 控制思考深度并占用
``max_completion_tokens`` 预算；普通模型改用采样温度 + 输出/提示预算。
本模块只生成参数字典，不实例化模型，也不修改 ``llm/factory.py``。
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ReasoningEffort(str, Enum):
    """推理努力程度，映射到推理模型的 reasoning_effort。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReasoningConfig(BaseModel):
    """推理预算配置。

    Attributes:
        reasoning_effort: low/medium/high 三档推理努力。
        max_cot_tokens: 思维链长度上限（推理模型的输出预算）。
        prompt_budget_tokens: 普通模型的提示/输出预算。
        expose_chain_of_thought: 是否请求返回思维链摘要（如 o3 的 summary）。
    """

    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    max_cot_tokens: int = Field(default=2048, ge=1)
    prompt_budget_tokens: int = Field(default=4096, ge=1)
    expose_chain_of_thought: bool = False

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _coerce_effort(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


_REASONING_MARKERS = ("o1", "o3", "o4", "r1", "qwq", "thinking")


def is_reasoning_model(name: str) -> bool:
    """按模型名/厂商名判断是否属于 o1/R1 类推理模型。"""
    lowered = (name or "").lower()
    if "reasoning" in lowered:
        return True
    for marker in _REASONING_MARKERS:
        if re.search(rf"(?:^|[-_/]){re.escape(marker)}(?:[-_\d.]|$)", lowered):
            return True
    return False


_TEMPERATURE = {
    ReasoningEffort.LOW: 0.0,
    ReasoningEffort.MEDIUM: 0.2,
    ReasoningEffort.HIGH: 0.7,
}


def build_reasoning_model_kwargs(
    provider: str,
    config: ReasoningConfig | None = None,
    *,
    model: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """生成传给 ``ChatOpenAI`` 等模型构造器的参数字典。

    Args:
        provider: 厂商或模型标识；同时用于判断是否推理模型。
        config: 推理配置；缺省用默认配置。
        model: 显式模型名，优先于 provider 作为 ``model`` 值。
        **overrides: 最后覆盖生成的参数（便于调用方微调）。

    Returns:
        仅含受支持参数的参数字典：推理模型用
        ``reasoning_effort`` + ``max_completion_tokens``；普通模型用
        ``temperature`` + ``max_tokens``。
    """
    cfg = config or ReasoningConfig()
    model_name = model or provider

    if is_reasoning_model(model_name) or is_reasoning_model(provider):
        kwargs: dict[str, Any] = {
            "model": model_name,
            "reasoning_effort": cfg.reasoning_effort.value,
            "max_completion_tokens": cfg.max_cot_tokens,
        }
        if cfg.expose_chain_of_thought:
            kwargs["reasoning_summary"] = "detailed"
    else:
        kwargs = {
            "model": model_name,
            "temperature": _TEMPERATURE[cfg.reasoning_effort],
            "max_tokens": cfg.prompt_budget_tokens,
        }

    kwargs.update(overrides)
    return kwargs
