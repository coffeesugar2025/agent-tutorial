"""SLO / 告警规则 / 健康探测（可观测性增强，不修改 metrics.py）。

- ``SLO``：目标阈值（成功率高好 / 延迟低好）。
- ``AlertRule``：对指标快照中的 P99 / 错误率等做阈值判断。
- ``AlertManager``：汇总规则与 SLO 的评估结果，产出告警列表。
- ``HealthProbe``：注册依赖探活函数（同步 / 异步），统一执行并汇总。
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

Check = Callable[[], bool | Awaitable[bool]]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def resolve_metric(snapshot: Mapping[str, Any], key: str) -> float | None:
    """从指标快照取数：先查顶层，再递归查 summary 等嵌套字典。"""
    if key in snapshot:
        value = _number(snapshot[key])
        if value is not None:
            return value
    for value in snapshot.values():
        if isinstance(value, Mapping):
            found = _find_in_mapping(value, key)
            if found is not None:
                return found
    return None


def _find_in_mapping(mapping: Mapping[str, Any], key: str) -> float | None:
    if key in mapping:
        value = _number(mapping[key])
        if value is not None:
            return value
    for value in mapping.values():
        if isinstance(value, Mapping):
            found = _find_in_mapping(value, key)
            if found is not None:
                return found
    return None


def _compare(value: float, op: str, threshold: float) -> bool:
    return {
        ">": value > threshold,
        ">=": value >= threshold,
        "<": value < threshold,
        "<=": value <= threshold,
        "==": value == threshold,
    }.get(op, value >= threshold)


@dataclass
class SLO:
    """服务等级目标：``comparison='>='`` 表示越大越好，``'<='`` 表示越小越好。"""

    name: str
    target: float
    metric: str = "success_rate"
    comparison: str = ">="

    def __post_init__(self) -> None:
        self.target = float(self.target)

    def is_met(self, value: float) -> bool:
        return _compare(value, self.comparison, self.target)


@dataclass
class Alert:
    """一条告警。"""

    name: str
    metric: str
    value: float
    threshold: float
    severity: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "metric": self.metric,
                "value": round(self.value, 4), "threshold": self.threshold,
                "severity": self.severity, "message": self.message}


@dataclass
class AlertRule:
    """阈值告警规则：当指标满足 ``metric op threshold`` 时触发。"""

    name: str
    metric: str
    threshold: float
    op: str = ">"
    severity: str = "warning"

    def __post_init__(self) -> None:
        self.threshold = float(self.threshold)

    def evaluate(self, snapshot: Mapping[str, Any]) -> Alert | None:
        value = resolve_metric(snapshot, self.metric)
        if value is None or not _compare(value, self.op, self.threshold):
            return None
        return Alert(
            name=self.name, metric=self.metric, value=value,
            threshold=self.threshold, severity=self.severity,
            message=f"{self.metric}={value:.4f} {self.op} {self.threshold}",
        )


class AlertManager:
    """按告警规则与 SLO 评估指标快照，产出告警列表。"""

    def __init__(self, rules: list[AlertRule] | None = None,
                 slos: list[SLO] | None = None) -> None:
        self.rules = list(rules or [])
        self.slos = list(slos or [])

    def evaluate(self, metrics_snapshot: Mapping[str, Any]) -> list[Alert]:
        alerts: list[Alert] = []
        for rule in self.rules:
            alert = rule.evaluate(metrics_snapshot)
            if alert is not None:
                alerts.append(alert)
        for slo in self.slos:
            value = resolve_metric(metrics_snapshot, slo.metric)
            if value is None or slo.is_met(value):
                continue
            alerts.append(Alert(
                name=f"{slo.name}_slo", metric=slo.metric, value=value,
                threshold=slo.target, severity="critical",
                message=f"SLO {slo.name} 未达标：{slo.metric}={value:.4f} "
                        f"{slo.comparison} {slo.target}",
            ))
        return alerts


class HealthProbe:
    """依赖探活注册表：注册 check 函数，统一执行并汇总健康状态。"""

    def __init__(self) -> None:
        self._checks: dict[str, Check] = {}

    def register(self, name: str, check: Check) -> Check:
        self._checks[name] = check
        return check

    def unregister(self, name: str) -> bool:
        return self._checks.pop(name, None) is not None

    def names(self) -> list[str]:
        return sorted(self._checks)

    async def check_all(self) -> dict[str, bool]:
        """并发执行全部探活；check 抛异常视为不健康。"""
        async def run(name: str, check: Check) -> tuple[str, bool]:
            try:
                result = check()
                if inspect.isawaitable(result):
                    result = await result
                return name, bool(result)
            except Exception:
                return name, False

        pairs = await asyncio.gather(
            *(run(name, check) for name, check in self._checks.items())
        )
        return dict(pairs)

    async def is_healthy(self) -> bool:
        return all((await self.check_all()).values())


__all__ = [
    "SLO", "AlertRule", "Alert", "AlertManager", "HealthProbe", "resolve_metric",
]
