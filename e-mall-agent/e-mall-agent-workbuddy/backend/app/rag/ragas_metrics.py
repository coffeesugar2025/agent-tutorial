"""RAG 专属评测指标（RAGAS 四项指标的本地可计算版本）。

不依赖 LLM 或网络，采用「词面覆盖 + 哈希语义相似度 + 覆盖度」的确定性近似：

- Faithfulness（忠实度）：答案中每个句子被上下文支撑的程度。
- Answer Relevancy（答案相关性）：答案对问题的覆盖与语义相似度。
- Context Precision（上下文精确率）：按排序位置加权的上下文相关比例。
- Context Recall（上下文召回率）：参考答案中的信息被上下文覆盖的比例。

``evaluate_rag`` 统一计算四项并返回 :class:`RagasReport`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .embeddings import HashEmbeddings
from .hybrid import bm25_tokenize

_SENTENCE_RE = re.compile(r"[。！？!?；;\n]+")


def _as_text(item: Any) -> str:
    """把字符串 / 检索结果对象 / 字典统一转成文本。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("content", item.get("page_content", "")))
    for attr in ("content", "page_content"):
        value = getattr(item, attr, None)
        if value is not None:
            return str(value)
    return str(item)


class _Similarity:
    """共享的词面 + 哈希语义相似度计算器。"""

    def __init__(self) -> None:
        self._embeddings = HashEmbeddings()

    def lexical(self, text: str, reference: str) -> float:
        """text 的 token（按长度加权）有多少出现在 reference 中。"""
        tokens = bm25_tokenize(text)
        if not tokens:
            return 0.0
        ref_tokens = set(bm25_tokenize(reference))
        total = sum(len(t) for t in tokens) or 1
        hit = sum(len(t) for t in tokens if t in ref_tokens)
        return min(1.0, hit / total)

    def semantic(self, text: str, reference: str) -> float:
        """哈希 embedding 的余弦相似度（向量已归一化，点积即余弦）。"""
        vec_a = self._embeddings.embed_query(text)
        vec_b = self._embeddings.embed_query(reference)
        return max(0.0, min(1.0, sum(a * b for a, b in zip(vec_a, vec_b))))

    def combined(self, text: str, reference: str) -> float:
        return 0.5 * self.lexical(text, reference) + 0.5 * self.semantic(text, reference)


_SIM = _Similarity()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text or "") if part.strip()]


@dataclass
class Faithfulness:
    """忠实度：答案各句被某条上下文支撑的最大程度，再取平均。"""

    def score(self, answer: str, contexts: Sequence[str]) -> float:
        sentences = _sentences(answer)
        if not sentences or not contexts:
            return 0.0
        total = 0.0
        for sentence in sentences:
            total += max(_SIM.combined(sentence, context) for context in contexts)
        return min(1.0, total / len(sentences))


@dataclass
class AnswerRelevancy:
    """答案相关性：答案对问题词面的覆盖（主）+ 语义相似度（辅）。"""

    def score(self, question: str, answer: str) -> float:
        if not question or not answer:
            return 0.0
        return min(1.0, 0.6 * _SIM.lexical(question, answer)
                   + 0.4 * _SIM.semantic(question, answer))


@dataclass
class ContextPrecision:
    """上下文精确率：按 1/rank 加权的上下文相关比例，抑制低质量长列表。"""

    relevance_threshold: float = 0.15

    def score(self, question: str, contexts: Sequence[str]) -> float:
        if not contexts:
            return 0.0
        weighted_hits = 0.0
        weight_sum = 0.0
        for rank, context in enumerate(contexts, start=1):
            relevant = 1.0 if _SIM.combined(question, context) >= self.relevance_threshold else 0.0
            weight = 1.0 / rank
            weighted_hits += relevant * weight
            weight_sum += weight
        return min(1.0, weighted_hits / weight_sum) if weight_sum else 0.0


@dataclass
class ContextRecall:
    """上下文召回率：参考答案 token 被上下文整体覆盖的比例。"""

    def score(self, ground_truth: str, contexts: Sequence[str]) -> float:
        tokens = bm25_tokenize(ground_truth)
        if not tokens or not contexts:
            return 0.0
        joined = " ".join(contexts)
        ref_tokens = set(bm25_tokenize(joined))
        total = sum(len(t) for t in tokens) or 1
        hit = sum(len(t) for t in tokens if t in ref_tokens)
        return min(1.0, hit / total)


@dataclass
class RagasReport:
    """四项指标的评测报告。"""

    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    ground_truth_provided: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevancy": round(self.answer_relevancy, 4),
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            "ground_truth_provided": self.ground_truth_provided,
        }

    def mean(self) -> float:
        """四项指标的算术平均，便于做单一门槛比较。"""
        return (self.faithfulness + self.answer_relevancy
                + self.context_precision + self.context_recall) / 4.0


def evaluate_rag(
    question: str,
    answer: str,
    contexts: Iterable[Any],
    ground_truth: str | None = None,
) -> RagasReport:
    """计算 RAGAS 四项本地指标。

    Args:
        question: 用户问题。
        answer: 系统答案。
        contexts: 召回的上下文（字符串、字典或检索结果对象）。
        ground_truth: 参考答案。为 None 时以问题作为召回率参考代理，并标记。
    """
    text_contexts = [_as_text(c) for c in contexts]
    text_contexts = [c for c in text_contexts if c]
    reference = ground_truth if ground_truth is not None else question
    return RagasReport(
        faithfulness=Faithfulness().score(answer, text_contexts),
        answer_relevancy=AnswerRelevancy().score(question, answer),
        context_precision=ContextPrecision().score(question, text_contexts),
        context_recall=ContextRecall().score(reference, text_contexts),
        ground_truth_provided=ground_truth is not None,
        details={"question": question, "context_count": len(text_contexts)},
    )


__all__ = [
    "Faithfulness", "AnswerRelevancy", "ContextPrecision", "ContextRecall",
    "RagasReport", "evaluate_rag",
]
