"""Release gate comparing a current eval report against a baseline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evaluator import EvalReport


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    pass_rate_delta: float = 0.0
    baseline_pass_rate: float = 0.0
    current_pass_rate: float = 0.0
    baseline_p95_ms: float = 0.0
    current_p95_ms: float = 0.0
    p95_delta_ratio: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed, "reasons": list(self.reasons),
            "pass_rate_delta": round(self.pass_rate_delta, 4),
            "baseline_pass_rate": round(self.baseline_pass_rate, 4),
            "current_pass_rate": round(self.current_pass_rate, 4),
            "baseline_p95_ms": round(self.baseline_p95_ms, 3),
            "current_p95_ms": round(self.current_p95_ms, 3),
            "p95_delta_ratio": round(self.p95_delta_ratio, 4),
        }


class RegressionGate:
    """Fail when pass rate drops or P95 latency degrades beyond thresholds."""

    def __init__(self, pass_rate_drop_threshold: float = 0.05,
                 p95_degradation_threshold: float = 0.20) -> None:
        self.pass_rate_drop_threshold = pass_rate_drop_threshold
        self.p95_degradation_threshold = p95_degradation_threshold

    def check(self, baseline: EvalReport, current: EvalReport) -> GateResult:
        delta = baseline.pass_rate - current.pass_rate
        base_p95 = baseline.p95_latency_ms
        current_p95 = current.p95_latency_ms
        ratio = (current_p95 - base_p95) / base_p95 if base_p95 > 0 else 0.0

        reasons: list[str] = []
        if delta > self.pass_rate_drop_threshold:
            reasons.append(
                f"通过率下降 {delta:.2%}，超过阈值 {self.pass_rate_drop_threshold:.2%}"
            )
        if base_p95 > 0 and ratio > self.p95_degradation_threshold:
            reasons.append(
                f"P95 延迟劣化 {ratio:.2%}，超过阈值 {self.p95_degradation_threshold:.2%}"
            )
        return GateResult(
            passed=not reasons, reasons=reasons,
            pass_rate_delta=delta,
            baseline_pass_rate=baseline.pass_rate,
            current_pass_rate=current.pass_rate,
            baseline_p95_ms=base_p95, current_p95_ms=current_p95,
            p95_delta_ratio=ratio,
        )

    evaluate = check


__all__ = ["RegressionGate", "GateResult"]
