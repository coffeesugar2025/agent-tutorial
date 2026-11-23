"""LLM-as-Judge：用可注入裁判函数按 rubric 对答案打分，并度量与人工标注的一致性。

默认裁判是本地确定性近似（rubric 关键字符覆盖率），真实模型通过 ``judge`` /
``model`` 注入；打分器遵循 ``evaluator.Scorer`` 协议，可注册进现有 Evaluator。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

# 裁判函数签名：(answer, rubric) -> 原始分数
JudgeFn = Callable[[str, str], float]

_STOPWORDS = (
    "回答", "答案", "输出", "给出", "说明", "描述", "需要", "应该", "要求",
    "包含", "包括", "准确", "完整", "简洁", "清晰", "礼貌", "专业", "相关",
    "正确", "有用", "是否", "以及", "并且", "内容", "请", "的", "和", "与",
    "及", "或", "需", "要",
)


def _word_char(char: str) -> bool:
    return char.isalnum() or "\u4e00" <= char <= "\u9fff"


def default_judge(answer: str, rubric: str) -> float:
    """本地确定性近似裁判：rubric 去掉套话后的关键字/字符在答案中的覆盖率。"""
    text = str(rubric).lower()
    for word in _STOPWORDS:
        text = text.replace(word, " ")
    chars = {c for c in text if _word_char(c)}
    if not chars:
        return 1.0 if str(answer).strip() else 0.0
    answer_text = str(answer).lower()
    return sum(1 for c in chars if c in answer_text) / len(chars)


@dataclass
class JudgeConfig:
    """裁判配置：评分 rubric、原始分数范围以及可注入的裁判函数/模型。"""

    rubric: str = ""
    min_score: float = 0.0
    max_score: float = 1.0
    judge: JudgeFn | None = None
    model: Any = None  # 可调用模型对象；当 judge 为空时作为裁判接入

    def __post_init__(self) -> None:
        if self.max_score <= self.min_score:
            raise ValueError("max_score 必须大于 min_score")

    def resolve_judge(self) -> JudgeFn:
        """按注入优先级返回裁判函数：judge > model > 默认本地裁判。"""
        candidate = self.judge if self.judge is not None else self.model
        if callable(candidate):
            return candidate  # type: ignore[return-value]
        return default_judge

    def normalise(self, raw: float) -> float:
        """把原始分数线性归一化到 [0, 1]，与 Evaluator 阈值语义对齐。"""
        value = (float(raw) - self.min_score) / (self.max_score - self.min_score)
        return min(1.0, max(0.0, value))


def _answer_text(actual: Any) -> str:
    if isinstance(actual, Mapping):
        for key in ("answer", "output", "text", "content"):
            if key in actual:
                return str(actual[key])
        import json
        return json.dumps(actual, ensure_ascii=False, default=str)
    return str(actual)


class LLMJudgeScorer:
    """按 rubric 调用裁判函数打分；实现 ``(actual, expected) -> float`` 协议。"""

    scorer_name = "llm_judge"

    def __init__(self, config: JudgeConfig | None = None,
                 judge: JudgeFn | None = None, rubric: str = "") -> None:
        self.config = config or JudgeConfig(rubric=rubric, judge=judge)
        if judge is not None:
            self.config.judge = judge
        if rubric:
            self.config.rubric = rubric

    def __call__(self, actual: Any, expected: Any = None) -> float:
        rubric = self.config.rubric if expected is None else str(expected)
        if not rubric:
            rubric = self.config.rubric
        raw = float(self.config.resolve_judge()(_answer_text(actual), rubric))
        return self.config.normalise(raw)

    # Evaluator 及外部可显式调用
    score = __call__
    evaluate = __call__


def register(evaluator: Any, name: str = LLMJudgeScorer.scorer_name,
             config: JudgeConfig | None = None,
             judge: JudgeFn | None = None) -> LLMJudgeScorer:
    """把 LLM 裁判打分器注册进现有 Evaluator（复用其 register_scorer 接口）。"""
    scorer = LLMJudgeScorer(config=config, judge=judge)
    evaluator.register_scorer(name, scorer)
    return scorer


@dataclass
class JudgeAgreement:
    """裁判分与人工分的 Pearson 相关系数及一致率。"""

    pearson: float = 0.0
    agreement: float = 0.0
    n: int = 0

    def __float__(self) -> float:
        return self.pearson

    def as_dict(self) -> dict[str, Any]:
        return {
            "pearson": round(self.pearson, 4),
            "agreement": round(self.agreement, 4),
            "n": self.n,
        }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    num = sum(a * b for a, b in zip(dx, dy))
    den = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    return min(1.0, max(-1.0, num / den)) if den else 0.0


def judge_consistency(judge_scores: Sequence[float],
                      human_scores: Sequence[float],
                      tolerance: float = 0.25) -> JudgeAgreement:
    """计算裁判分与人工标注的一致性（Pearson + 差值在容差内的比例）。"""
    left, right = list(judge_scores), list(human_scores)
    if len(left) != len(right):
        raise ValueError("judge_scores 与 human_scores 长度不一致")
    if not left:
        return JudgeAgreement()
    agreement = sum(
        1 for j, h in zip(left, right) if abs(float(j) - float(h)) <= tolerance
    ) / len(left)
    return JudgeAgreement(pearson=_pearson(left, right), agreement=agreement,
                          n=len(left))


__all__ = [
    "JudgeConfig", "LLMJudgeScorer", "JudgeAgreement", "default_judge",
    "judge_consistency", "register",
]
