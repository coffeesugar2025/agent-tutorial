"""错误归因与 bad case 闭环：分类 -> 人工标注 -> 入 golden 集 -> 回归门禁。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping

from .dataset import CaseDataset, GoldenCase
from .evaluator import EvalReport
from .regression import GateResult, RegressionGate

Rule = Callable[[Any, Any, Any], "ErrorCategory | AttributionResult | None"]


class ErrorCategory(str, Enum):
    """失败归因类别。"""

    RETRIEVAL = "retrieval"
    PLANNING = "planning"
    TOOL = "tool"
    GENERATION = "generation"
    PERMISSION = "permission"
    CONFIG = "config"


@dataclass
class AttributionResult:
    """归因结论：类别、依据说明、置信度与证据。"""

    category: ErrorCategory
    reason: str = ""
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value, "reason": self.reason,
            "confidence": round(self.confidence, 4), "evidence": self.evidence,
        }


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float)))
    return str(value or "")


def _default_rules(case: Any, result: Any, trace: Any) -> ErrorCategory | None:
    """内置启发式规则：按错误文本与评分细节归类，命中即返回。"""
    error = _text(result.get("error")) if isinstance(result, Mapping) else str(getattr(result, "error", ""))
    detail = result.get("detail", {}) if isinstance(result, Mapping) else getattr(result, "detail", {}) or {}
    lowered = error.lower() + " " + _text(trace).lower()

    if any(word in lowered for word in ("permission", "forbidden", "403", "权限", "越权", "unauthor")):
        return ErrorCategory.PERMISSION
    if any(word in lowered for word in ("未注册工具", "not registered", "unknown tool", "配置", "config", "secret", "api key")):
        return ErrorCategory.CONFIG
    if any(word in lowered for word in ("tool", "工具", "retriev", "检索", "recall")):
        return ErrorCategory.RETRIEVAL if any(w in lowered for w in ("retriev", "检索", "recall")) else ErrorCategory.TOOL
    if isinstance(detail, Mapping) and detail.get("tool_called") == 0.0:
        return ErrorCategory.TOOL
    if isinstance(detail, Mapping) and detail.get("route_match") == 0.0:
        return ErrorCategory.PLANNING
    return ErrorCategory.GENERATION


def classify_error(case: Any, result: Any, trace: Any = None,
                   rules: list[Rule] | None = None) -> AttributionResult:
    """按可注入规则列表归因；规则返回 None 时继续尝试下一条。"""
    for rule in (rules if rules is not None else [_default_rules]):
        outcome: Any = rule(case, result, trace)
        if outcome is None:
            continue
        if isinstance(outcome, AttributionResult):
            return outcome
        return AttributionResult(category=ErrorCategory(outcome))
    return AttributionResult(category=ErrorCategory.GENERATION, reason="未命中任何规则，默认归为生成问题")


@dataclass
class Annotation:
    """人工标注：修正后的期望、归因类别、备注与标注人。"""

    expected: Any = None
    category: ErrorCategory | None = None
    note: str = ""
    annotator: str = ""


@dataclass
class BadCase:
    """待闭环的 bad case。"""

    id: str
    case: GoldenCase
    status: str = "submitted"
    attribution: AttributionResult | None = None
    annotation: Annotation | None = None
    promoted_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status,
            "case": self.case.to_dict(),
            "attribution": self.attribution.as_dict() if self.attribution else None,
            "annotation": {
                "expected": self.annotation.expected,
                "category": self.annotation.category.value if self.annotation and self.annotation.category else None,
                "note": self.annotation.note if self.annotation else "",
                "annotator": self.annotation.annotator if self.annotation else "",
            } if self.annotation else None,
            "promoted_id": self.promoted_id,
        }


class FeedbackLoop:
    """bad case 到 golden 集与回归门禁的闭环管理器（内存态，确定性可测）。"""

    def __init__(self, rules: list[Rule] | None = None,
                 gate: RegressionGate | None = None) -> None:
        self.rules = rules
        self.gate = gate or RegressionGate()
        self.bad_cases: dict[str, BadCase] = {}
        self.golden = CaseDataset()

    def submit_bad_case(self, case: GoldenCase, result: Any = None,
                        trace: Any = None,
                        category: ErrorCategory | None = None) -> BadCase:
        """登记 bad case 并完成自动归因。"""
        attribution = AttributionResult(category=category) if category else \
            classify_error(case, result, trace, self.rules)
        bad = BadCase(id=case.id, case=case, attribution=attribution)
        self.bad_cases[bad.id] = bad
        return bad

    def annotate(self, bad_case_id: str, annotation: Annotation | None = None,
                 **kwargs: Any) -> BadCase:
        """人工标注：接受 Annotation 对象或直接传入字段。"""
        bad = self.bad_cases[bad_case_id]
        bad.annotation = annotation or Annotation(**kwargs)
        bad.status = "annotated"
        return bad

    def promote_to_golden(self, bad_case_id: str,
                          dataset: CaseDataset | None = None) -> GoldenCase:
        """把已标注 case 提升为 golden case，并加入回归数据集。"""
        bad = self.bad_cases[bad_case_id]
        annotation = bad.annotation
        expected = annotation.expected if annotation and annotation.expected is not None else bad.case.expected
        tags = list(bad.case.tags)
        if "promoted" not in tags:
            tags.append("promoted")
        metadata = dict(bad.case.metadata)
        metadata.update({
            "source_bad_case": bad.id,
            "category": bad.attribution.category.value if bad.attribution else "",
            "annotation_note": annotation.note if annotation else "",
        })
        golden = GoldenCase(
            id=f"golden-{bad.id}", name=bad.case.name, input=bad.case.input,
            expected=expected, tags=tags, metadata=metadata,
        )
        self.golden.add(golden)
        if dataset is not None:
            dataset.add(golden)
        bad.promoted_id = golden.id
        bad.status = "promoted"
        return golden

    def regression_gate(self, baseline: EvalReport,
                        current: EvalReport) -> GateResult:
        """把提升后的 golden 集纳入回归门禁判断。"""
        return self.gate.check(baseline, current)

    check = regression_gate

    def pending(self) -> list[BadCase]:
        """返回尚未提升进 golden 集的 bad case。"""
        return [b for b in self.bad_cases.values() if b.status != "promoted"]


__all__ = [
    "ErrorCategory", "AttributionResult", "Annotation", "BadCase",
    "classify_error", "FeedbackLoop",
]
