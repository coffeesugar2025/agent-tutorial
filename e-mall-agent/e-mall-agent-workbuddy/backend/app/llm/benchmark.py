"""模型选型 Benchmark：能力/成本/延迟三维加权决策。

先按硬性约束（最低质量分、最大 P99、预算上限）筛选，再对通过筛选的候选
在三个维度上归一化并加权打分，输出可读的选型理由。纯计算、无网络依赖。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class ModelProfile(BaseModel):
    """单个模型的能力、成本与延迟画像。"""

    name: str
    quality: float = Field(ge=0, le=10, description="综合质量分（0~10）")
    cost_per_1m: float = Field(ge=0, description="每百万 token 成本（美元）")
    p99_latency_ms: float = Field(gt=0, description="P99 延迟（毫秒）")


class ModelRequirements(BaseModel):
    """选型需求：硬性门槛 + 三维权重。"""

    min_quality: float = 0.0
    max_cost_per_1m: float | None = None
    max_p99_ms: float | None = None
    weights: dict[str, float] = Field(
        default_factory=lambda: {"quality": 0.5, "cost": 0.25, "latency": 0.25}
    )

    @model_validator(mode="after")
    def _validate(self) -> "ModelRequirements":
        allowed = {"quality", "cost", "latency"}
        if not self.weights or not set(self.weights) <= allowed:
            raise ValueError("weights 只能包含 quality/cost/latency 且不能为空")
        if any(value < 0 for value in self.weights.values()):
            raise ValueError("weights 不能为负")
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("weights 之和必须大于 0")
        self.weights = {key: value / total for key, value in self.weights.items()}
        return self


class ModelSelection(BaseModel):
    """选型结果与可读理由。"""

    profile: ModelProfile
    score: float
    reasons: list[str] = Field(default_factory=list)
    eligible_count: int = 0

    @property
    def reason(self) -> str:
        """把理由列表拼成一段可直接展示的中文说明。"""
        return "；".join(self.reasons)


def select_model(
    profiles: list[ModelProfile], requirements: ModelRequirements | None = None
) -> ModelSelection:
    """按需求选出加权得分最高的模型。

    Raises:
        ValueError: 候选为空，或没有模型满足全部硬性约束。
    """
    req = requirements or ModelRequirements()
    if not profiles:
        raise ValueError("模型候选列表不能为空")

    eligible = [
        p for p in profiles
        if p.quality >= req.min_quality
        and (req.max_cost_per_1m is None or p.cost_per_1m <= req.max_cost_per_1m)
        and (req.max_p99_ms is None or p.p99_latency_ms <= req.max_p99_ms)
    ]
    if not eligible:
        raise ValueError(
            f"没有模型满足硬性约束（最低质量 {req.min_quality}、"
            f"成本上限 {req.max_cost_per_1m}、P99 上限 {req.max_p99_ms}）"
        )

    max_quality = max(p.quality for p in eligible) or 1.0
    min_cost = min(p.cost_per_1m for p in eligible)
    min_latency = min(p.p99_latency_ms for p in eligible)

    def score_of(p: ModelProfile) -> float:
        quality_norm = p.quality / max_quality
        cost_norm = (min_cost / p.cost_per_1m) if p.cost_per_1m > 0 else 1.0
        latency_norm = min_latency / p.p99_latency_ms
        return (
            req.weights.get("quality", 0.0) * quality_norm
            + req.weights.get("cost", 0.0) * cost_norm
            + req.weights.get("latency", 0.0) * latency_norm
        )

    scored = sorted(
        ((p, score_of(p)) for p in eligible),
        key=lambda item: (-item[1], item[0].cost_per_1m, item[0].p99_latency_ms, item[0].name),
    )
    winner, score = scored[0]

    reasons = [
        f"共 {len(eligible)}/{len(profiles)} 个候选通过硬性约束",
        f"质量分 {winner.quality:.1f} ≥ 门槛 {req.min_quality:.1f}",
    ]
    if req.max_p99_ms is not None:
        reasons.append(f"P99 {winner.p99_latency_ms:.0f}ms ≤ 上限 {req.max_p99_ms:.0f}ms")
    if req.max_cost_per_1m is not None:
        reasons.append(f"成本 {winner.cost_per_1m:g} ≤ 预算 {req.max_cost_per_1m:g}")
    weights = req.weights
    reasons.append(
        f"加权总分 {score:.3f} 最高（质量 {weights.get('quality', 0.0):.2f} / "
        f"成本 {weights.get('cost', 0.0):.2f} / 延迟 {weights.get('latency', 0.0):.2f}）"
    )
    return ModelSelection(
        profile=winner, score=score, reasons=reasons, eligible_count=len(eligible)
    )
