"""Evaluation framework: golden datasets, scorers, replay and regression gates."""
from .dataset import CaseDataset, GoldenCase
from .evaluator import (
    BUILTIN_SCORERS,
    EvalCaseResult,
    EvalReport,
    Evaluator,
)
from .regression import GateResult, RegressionGate
from .replay import ReplayResult, ReplayRunner, ReplayStep

__all__ = [
    "GoldenCase", "CaseDataset", "Evaluator", "EvalReport", "EvalCaseResult",
    "BUILTIN_SCORERS", "ReplayRunner", "ReplayResult", "ReplayStep",
    "RegressionGate", "GateResult",
]
