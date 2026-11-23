"""轨迹评测：基于 ReplayRunner.diff 比较期望与实际工具调用序列。

不修改 dataset.py，通过 ``with_trajectory`` 生成携带 ``expected_trajectory``
元数据的 GoldenCase 增强副本；打分器遵循 Evaluator 的 scorer 协议。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .dataset import GoldenCase
from .replay import ReplayResult, ReplayRunner

SCORER_NAME = "trajectory"
TRAJECTORY_KEY = "expected_trajectory"


def _tool_sequence(value: Any) -> list[str]:
    """把工具名列表 / trace 事件 / ReplayResult 统一成工具序列。"""
    if isinstance(value, ReplayResult):
        return list(value.tool_sequence)
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        for key in (TRAJECTORY_KEY, "tool_sequence", "tools", "tools_used"):
            if key in value:
                return _tool_sequence(value[key])
        if "events" in value:
            return list(ReplayRunner().replay(value["events"]).tool_sequence)
        return []
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, str) for item in value):
            return list(value)
        return list(ReplayRunner().replay(value).tool_sequence)
    seq = getattr(value, "tool_sequence", None)
    return _tool_sequence(seq) if seq is not None else []


def _as_events(sequence: Sequence[str]) -> list[dict[str, Any]]:
    """将工具序列转成 replay 可识别的伪事件，以复用其 diff 逻辑。"""
    return [
        {"ts": float(i), "trace_id": "trajectory", "node": "agent",
         "event": "tool_call", "payload": {"tool": tool}}
        for i, tool in enumerate(sequence)
    ]


def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    """最长公共子序列长度（顺序敏感的部分匹配）。"""
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right):
            current.append(
                previous[index] + 1 if item == other
                else max(current[index], previous[index + 1])
            )
        previous = current
    return previous[-1]


@dataclass
class TrajectoryResult:
    """轨迹评分结果与 diff 细节。"""

    score: float
    match: bool
    expected_sequence: list[str] = field(default_factory=list)
    actual_sequence: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4), "match": self.match,
            "expected_sequence": self.expected_sequence,
            "actual_sequence": self.actual_sequence, "detail": self.detail,
        }


class TrajectoryScorer:
    """比较期望与实际工具序列；实现 ``(actual, expected) -> float`` 协议。"""

    def score(self, trace: Any, expected: Any) -> TrajectoryResult:
        want = _tool_sequence(expected)
        got = _tool_sequence(trace)
        detail = ReplayRunner().diff(_as_events(want), _as_events(got))
        longest = max(len(want), len(got))
        score = 1.0 if detail["match"] else (
            _lcs_length(want, got) / longest if longest else 1.0
        )
        return TrajectoryResult(
            score=score, match=detail["match"],
            expected_sequence=want, actual_sequence=got, detail=detail,
        )

    def __call__(self, actual: Any, expected: Any = None) -> float:
        return self.score(actual, expected).score

    evaluate = score


def trajectory_score(trace: Any, expected: Any) -> float:
    """便捷函数：返回轨迹匹配得分（完全一致 1.0，完全不一致 0.0）。"""
    return TrajectoryScorer().score(trace, expected).score


def with_trajectory(case: GoldenCase, sequence: Sequence[str]) -> GoldenCase:
    """返回增强副本，把期望轨迹存入 ``metadata['expected_trajectory']``。"""
    clone = GoldenCase(
        id=case.id, name=case.name, input=case.input, expected=case.expected,
        tags=list(case.tags), metadata=dict(case.metadata),
    )
    clone.metadata[TRAJECTORY_KEY] = list(sequence)
    return clone


def get_trajectory(case: GoldenCase) -> list[str]:
    """读取 ``with_trajectory`` 附加的期望轨迹。"""
    return _tool_sequence(case.metadata.get(TRAJECTORY_KEY, []))


def trajectory_expectation(case: GoldenCase) -> dict[str, Any]:
    """把期望轨迹包装成 Evaluator 可识别的 expectation。"""
    return {SCORER_NAME: get_trajectory(case)}


def register(evaluator: Any, name: str = SCORER_NAME,
             scorer: TrajectoryScorer | None = None) -> TrajectoryScorer:
    """把轨迹打分器注册进现有 Evaluator。"""
    instance = scorer or TrajectoryScorer()
    evaluator.register_scorer(name, instance)
    return instance


__all__ = [
    "TrajectoryScorer", "TrajectoryResult", "trajectory_score",
    "with_trajectory", "get_trajectory", "trajectory_expectation", "register",
]
