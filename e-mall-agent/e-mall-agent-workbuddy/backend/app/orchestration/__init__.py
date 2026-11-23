"""Agent 编排模式包：五类官方工作流模式的 LangGraph 实现。"""
from __future__ import annotations

from .factory import (
    ALL_PATTERNS,
    EVALUATOR_OPTIMIZER,
    ORCHESTRATOR_WORKERS,
    PARALLELIZATION,
    PROMPT_CHAINING,
    ROUTING,
    build_pattern,
)
from .models import Evaluation, SubTask, WorkerResult
from .patterns import (
    evaluator_optimizer_pattern,
    orchestrator_workers_pattern,
    parallel_pattern,
    prompt_chaining_pattern,
    routing_pattern,
)

__all__ = [
    "ALL_PATTERNS",
    "EVALUATOR_OPTIMIZER",
    "ORCHESTRATOR_WORKERS",
    "PARALLELIZATION",
    "PROMPT_CHAINING",
    "ROUTING",
    "Evaluation",
    "SubTask",
    "WorkerResult",
    "build_pattern",
    "evaluator_optimizer_pattern",
    "orchestrator_workers_pattern",
    "parallel_pattern",
    "prompt_chaining_pattern",
    "routing_pattern",
]
