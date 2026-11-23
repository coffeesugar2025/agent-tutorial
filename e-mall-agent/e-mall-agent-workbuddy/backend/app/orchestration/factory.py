"""编排模式工厂与官方五类模式名称常量。

名称对齐 Anthropic《Building effective agents》提出的五类工作流模式：
Prompt Chaining、Routing、Parallelization、Orchestrator-Workers、
Evaluator-Optimizer。``build_pattern`` 统一按名称构造对应 LangGraph 图。
"""
from __future__ import annotations

from typing import Any

from .patterns import (
    evaluator_optimizer_pattern,
    orchestrator_workers_pattern,
    parallel_pattern,
    prompt_chaining_pattern,
    routing_pattern,
)

PROMPT_CHAINING = "prompt_chaining"
ROUTING = "routing"
PARALLELIZATION = "parallelization"
ORCHESTRATOR_WORKERS = "orchestrator_workers"
EVALUATOR_OPTIMIZER = "evaluator_optimizer"

ALL_PATTERNS: tuple[str, ...] = (
    PROMPT_CHAINING,
    ROUTING,
    PARALLELIZATION,
    ORCHESTRATOR_WORKERS,
    EVALUATOR_OPTIMIZER,
)


def build_pattern(name: str, **kwargs: Any) -> Any:
    """按模式名称构造编译后的 LangGraph 图。

    Args:
        name: ``ALL_PATTERNS`` 中的模式名。
        **kwargs: 透传给对应模式工厂的参数。

    Raises:
        ValueError: 名称不在受支持的五类模式内。
    """
    builders = {
        PROMPT_CHAINING: prompt_chaining_pattern,
        ROUTING: routing_pattern,
        PARALLELIZATION: parallel_pattern,
        ORCHESTRATOR_WORKERS: orchestrator_workers_pattern,
        EVALUATOR_OPTIMIZER: evaluator_optimizer_pattern,
    }
    if name not in builders:
        raise ValueError(f"未知编排模式 {name!r}，可选: {', '.join(ALL_PATTERNS)}")
    return builders[name](**kwargs)
