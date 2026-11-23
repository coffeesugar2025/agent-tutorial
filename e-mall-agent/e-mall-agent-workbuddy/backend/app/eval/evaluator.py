"""Rule-based evaluation of golden cases against an async runner."""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .dataset import CaseDataset

Scorer = Callable[[Any, Any], float]


def _answer(actual: Any) -> str:
    if isinstance(actual, Mapping):
        for key in ("answer", "output", "text", "content"):
            if key in actual:
                return str(actual[key])
        return json.dumps(actual, ensure_ascii=False, default=str)
    return str(actual)


def _field(actual: Any, name: str) -> Any:
    if isinstance(actual, Mapping):
        return actual.get(name)
    return getattr(actual, name, None)


def _exact(actual: Any, expected: Any) -> float:
    return 1.0 if _answer(actual) == str(expected) else 0.0


def _contains(actual: Any, expected: Any) -> float:
    text = _answer(actual)
    needles = expected if isinstance(expected, (list, tuple, set)) else [expected]
    return 1.0 if all(str(n) in text for n in needles) else 0.0


def _json_path(actual: Any, expected: Any) -> float:
    """``expected`` = ``{"path": "$.a.b", "equals": value}`` or ``[path, value]``."""
    if isinstance(expected, (list, tuple)) and len(expected) == 2:
        path, wanted = expected
    elif isinstance(expected, Mapping):
        path, wanted = expected.get("path", "$"), expected.get("equals")
    else:
        path, wanted = str(expected), None

    node: Any = actual
    for part in str(path).lstrip("$").strip(".").split("."):
        if not part:
            continue
        if isinstance(node, Mapping):
            node = node.get(part)
        elif isinstance(node, (list, tuple)) and part.isdigit():
            idx = int(part)
            node = node[idx] if idx < len(node) else None
        else:
            node = None
        if node is None:
            break
    if wanted is None:
        return 1.0 if node is not None else 0.0
    return 1.0 if node == wanted else 0.0


def _route_match(actual: Any, expected: Any) -> float:
    return 1.0 if str(_field(actual, "route")) == str(expected) else 0.0


def _tool_called(actual: Any, expected: Any) -> float:
    names: set[str] = set()
    for key in ("tools_used", "tool_calls", "tools", "tool_names"):
        value = _field(actual, key)
        if isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, Mapping):
                    name = item.get("name") or item.get("tool")
                else:
                    name = item
                if name:
                    names.add(str(name))
        elif isinstance(value, Mapping):
            names.update(str(k) for k in value.keys())
        elif value:
            names.add(str(value))
    wanted = expected if isinstance(expected, (list, tuple, set)) else [expected]
    return 1.0 if all(str(w) in names for w in wanted) else 0.0


def _answer_length(actual: Any, expected: Any) -> float:
    length = len(_answer(actual))
    if isinstance(expected, Mapping):
        low = int(expected.get("min", 0))
        high = int(expected.get("max", 10**9))
    else:
        low, high = 0, int(expected)
    return 1.0 if low <= length <= high else 0.0


BUILTIN_SCORERS: dict[str, Scorer] = {
    "exact": _exact,
    "contains": _contains,
    "json_path": _json_path,
    "route_match": _route_match,
    "tool_called": _tool_called,
    "answer_length": _answer_length,
}


@dataclass
class EvalCaseResult:
    case_id: str
    name: str
    score: float
    passed: bool
    latency_ms: float
    tags: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "name": self.name,
            "score": round(self.score, 4), "passed": self.passed,
            "latency_ms": round(self.latency_ms, 3), "tags": self.tags,
            "detail": self.detail, "error": self.error,
        }


@dataclass
class EvalReport:
    total: int
    passed: int
    pass_rate: float
    per_case: list[EvalCaseResult] = field(default_factory=list)
    by_tag: dict[str, dict[str, Any]] = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total, "passed": self.passed,
            "pass_rate": round(self.pass_rate, 4),
            "per_case": [r.as_dict() for r in self.per_case],
            "by_tag": self.by_tag,
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "duration_ms": round(self.duration_ms, 3),
        }


class Evaluator:
    """Score a dataset with composable rule scorers."""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.scorers: dict[str, Scorer] = dict(BUILTIN_SCORERS)

    def register_scorer(self, name: str, scorer: Scorer) -> None:
        self.scorers[name] = scorer

    @staticmethod
    def _normalise_expected(expected: Any) -> list[Any]:
        if isinstance(expected, list):
            return expected
        if isinstance(expected, Mapping):
            if "type" in expected:
                return [expected]
            return [{k: v} for k, v in expected.items()]
        return [{"exact": expected}]

    def _resolve(self, expectation: Any) -> tuple[str, Any]:
        if isinstance(expectation, Mapping):
            if "type" in expectation:
                name = str(expectation["type"])
                payload = expectation.get("value", expectation.get("expected"))
                return name, payload
            for key in expectation:
                if key in self.scorers:
                    return key, expectation[key]
        raise KeyError(f"未知的评分类型: {expectation!r}")

    def score(self, actual: Any, expected: Any) -> tuple[float, dict[str, Any]]:
        expectations = self._normalise_expected(expected)
        if not expectations:
            return 1.0, {}
        details: dict[str, Any] = {}
        scores: list[float] = []
        for item in expectations:
            name, payload = self._resolve(item)
            value = float(self.scorers[name](actual, payload))
            scores.append(value)
            details[name] = round(value, 4)
        return sum(scores) / len(scores), details

    async def evaluate(self, dataset: CaseDataset, runner: Callable[..., Any],
                       input_only: bool = False) -> EvalReport:
        """Run every case (sequentially) and aggregate the results."""
        started = time.perf_counter()
        results: list[EvalCaseResult] = []
        by_tag: dict[str, dict[str, Any]] = {}
        latencies: list[float] = []

        for case in dataset:
            case_started = time.perf_counter()
            error = ""
            actual: Any = None
            try:
                payload = case.input if input_only else case
                actual = runner(payload)
                if inspect.isawaitable(actual):
                    actual = await actual
            except Exception as exc:  # noqa: BLE001 - a failing case is still reported
                error = f"{type(exc).__name__}: {exc}"
            latency = (time.perf_counter() - case_started) * 1000
            if isinstance(actual, Mapping) and actual.get("latency_ms") is not None:
                latency = float(actual["latency_ms"])

            score, detail = (0.0, {}) if error else self.score(actual, case.expected)
            passed = not error and score >= self.threshold
            result = EvalCaseResult(
                case_id=case.id, name=case.name, score=score, passed=passed,
                latency_ms=latency, tags=list(case.tags), detail=detail,
                error=error,
            )
            results.append(result)
            latencies.append(latency)
            for tag in case.tags:
                bucket = by_tag.setdefault(tag, {"total": 0, "passed": 0})
                bucket["total"] += 1
                if passed:
                    bucket["passed"] += 1

        for bucket in by_tag.values():
            bucket["pass_rate"] = round(
                bucket["passed"] / bucket["total"], 4
            ) if bucket["total"] else 0.0

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))] \
            if ordered else 0.0
        return EvalReport(
            total=total, passed=passed_count,
            pass_rate=passed_count / total if total else 0.0,
            per_case=results, by_tag=by_tag,
            avg_latency_ms=sum(latencies) / total if total else 0.0,
            p95_latency_ms=float(p95),
            duration_ms=(time.perf_counter() - started) * 1000,
        )


__all__ = [
    "Evaluator", "EvalReport", "EvalCaseResult", "BUILTIN_SCORERS",
]
