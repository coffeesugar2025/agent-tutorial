"""在线评测 / A-B 实验：用户分桶、指标记录与两样本显著性检验（标准库实现）。"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def _betacf(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数的连分数展开（Numerical Recipes）。"""
    max_iter, eps, tiny = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    result = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        result *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) < eps:
            break
    return result


def _betainc(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


@dataclass
class Experiment:
    """A-B 实验配置：按 user_id 稳定哈希分流到对照组 / 实验组。"""

    name: str
    control: str = "control"
    treatment: str = "treatment"
    treatment_ratio: float = 0.5
    salt: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.treatment_ratio <= 1.0:
            raise ValueError("treatment_ratio 必须在 [0, 1] 之间")

    @property
    def groups(self) -> tuple[str, str]:
        return self.control, self.treatment

    def assign(self, user_id: str) -> str:
        """用 SHA-256 哈希分桶，保证跨进程、跨调用稳定。"""
        digest = hashlib.sha256(f"{self.salt}:{user_id}".encode("utf-8")).hexdigest()
        bucket = int(digest[:16], 16) / float(0xFFFFFFFFFFFFFFFF)
        return self.treatment if bucket < self.treatment_ratio else self.control

    assign_group = assign


@dataclass
class SignificanceResult:
    """Welch 两样本 t 检验结果。"""

    t_statistic: float = 0.0
    p_value: float = 1.0
    significant: bool = False
    control_mean: float = 0.0
    treatment_mean: float = 0.0
    control_n: int = 0
    treatment_n: int = 0
    df: float = 0.0

    def __float__(self) -> float:
        return self.p_value

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_statistic": round(self.t_statistic, 4),
            "p_value": round(self.p_value, 6),
            "significant": self.significant,
            "control_mean": round(self.control_mean, 4),
            "treatment_mean": round(self.treatment_mean, 4),
            "control_n": self.control_n, "treatment_n": self.treatment_n,
            "df": round(self.df, 2),
        }


def significance_test(control: Sequence[float], treatment: Sequence[float],
                      alpha: float = 0.05) -> SignificanceResult:
    """Welch t 检验（不假设方差相等），p 值由完全 Beta 函数计算。"""
    left, right = list(control), list(treatment)
    n1, n2 = len(left), len(right)
    m1 = sum(left) / n1 if n1 else 0.0
    m2 = sum(right) / n2 if n2 else 0.0
    if n1 < 2 or n2 < 2:
        return SignificanceResult(control_mean=m1, treatment_mean=m2,
                                   control_n=n1, treatment_n=n2)

    v1 = sum((x - m1) ** 2 for x in left) / (n1 - 1)
    v2 = sum((x - m2) ** 2 for x in right) / (n2 - 1)
    a, b = v1 / n1, v2 / n2
    se2 = a + b
    result = SignificanceResult(control_mean=m1, treatment_mean=m2,
                                control_n=n1, treatment_n=n2)
    if se2 <= 0.0:
        result.t_statistic = 0.0 if m1 == m2 else math.copysign(float("inf"), m2 - m1)
        result.p_value = 1.0 if m1 == m2 else 0.0
        result.significant = m1 != m2
        return result

    t = (m2 - m1) / math.sqrt(se2)
    df = se2 ** 2 / (a * a / (n1 - 1) + b * b / (n2 - 1))
    p = _betainc(df / 2.0, 0.5, df / (df + t * t))
    result.t_statistic = t
    result.df = df
    result.p_value = min(1.0, max(0.0, p))
    result.significant = result.p_value < alpha
    return result


@dataclass
class ExperimentReport:
    """实验报告：分流样本量、均值差异与显著性结论。"""

    experiment: str
    metric: str
    test: SignificanceResult = field(default_factory=SignificanceResult)
    alpha: float = 0.05

    @property
    def lift(self) -> float:
        if self.test.control_mean == 0:
            return 0.0
        return (self.test.treatment_mean - self.test.control_mean) / abs(self.test.control_mean)

    @property
    def significant(self) -> bool:
        return self.test.significant

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment, "metric": self.metric,
            "alpha": self.alpha, "lift": round(self.lift, 4),
            **self.test.as_dict(),
        }


class ExperimentRunner:
    """按实验配置记录各分组指标，并生成实验报告。"""

    def __init__(self, experiment: Experiment) -> None:
        self.experiment = experiment
        self.records: dict[str, list[dict[str, float]]] = {
            experiment.control: [], experiment.treatment: [],
        }

    def record(self, group: str, metrics: Mapping[str, float]) -> None:
        """记录一条实验组指标；未知分组直接拒绝。"""
        if group not in self.experiment.groups:
            raise ValueError(f"未知实验分组: {group}")
        self.records.setdefault(group, []).append({k: float(v) for k, v in metrics.items()})

    def record_for_user(self, user_id: str, metrics: Mapping[str, float]) -> str:
        """按用户哈希分流后记录，返回实际分组。"""
        group = self.experiment.assign(user_id)
        self.record(group, metrics)
        return group

    def values(self, metric: str, group: str) -> list[float]:
        return [float(r[metric]) for r in self.records.get(group, []) if metric in r]

    def report(self, metric: str = "conversion",
               alpha: float = 0.05) -> ExperimentReport:
        control = self.values(metric, self.experiment.control)
        treatment = self.values(metric, self.experiment.treatment)
        return ExperimentReport(
            experiment=self.experiment.name, metric=metric,
            test=significance_test(control, treatment, alpha=alpha), alpha=alpha,
        )


__all__ = [
    "Experiment", "ExperimentRunner", "ExperimentReport",
    "SignificanceResult", "significance_test",
]
