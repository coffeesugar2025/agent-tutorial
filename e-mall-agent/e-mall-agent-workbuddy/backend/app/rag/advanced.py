"""高级 RAG 范式：Corrective / Self / Agentic 三种可控检索决策。

复用现有 ``pipeline``（默认检索）、``citation``（GroundednessScorer）、
``hybrid``（词面切词）以及 ``query``（规划拆分）；检索器、生成器、反射器、
规划器均可注入，便于纯本地确定性测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .citation import GroundednessScorer
from .hybrid import bm25_tokenize
from .pipeline import get_rag_pipeline
from .query import QueryDecomposer

Retriever = Callable[[str], list[Any]]
Answerer = Callable[[str, list[Any]], str]
ReflectionFn = Callable[[str], str]          # prompt -> 反射 token
Planner = Callable[[str], list[str]]
Decider = Callable[[str, str, list[Any]], bool]

_SENTENCE_RE = re.compile(r"[。！？!?；;\n]+")
_RETRIEVAL_KEYWORDS = (
    "退货", "退款", "配送", "包邮", "运费", "价格", "保修", "发票",
    "优惠", "订单", "商品", "多久", "多少", "怎么", "如何", "政策", "规则",
)


def _content(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("content", item.get("page_content", "")))
    return str(getattr(item, "content", None) or getattr(item, "page_content", "") or "")


def _as_context(item: Any) -> Any:
    """把字符串上下文包装成 GroundednessScorer 可识别的字典。"""
    return {"content": item} if isinstance(item, str) else item


def _default_retriever(query: str) -> list[Any]:
    return get_rag_pipeline().retrieve(query)


def _default_answerer(question: str, contexts: list[Any]) -> str:
    """抽取式答案：直接拼接前 3 条证据，保证默认输出可被上下文支撑。"""
    pieces = [_content(c) for c in contexts[:3] if _content(c)]
    if not pieces:
        return "知识库中没有足够的信息回答该问题。"
    return "；".join(pieces)


def _coverage(text: str, reference: str) -> float:
    tokens = bm25_tokenize(text)
    if not tokens:
        return 0.0
    ref = set(bm25_tokenize(reference))
    total = sum(len(t) for t in tokens) or 1
    return min(1.0, sum(len(t) for t in tokens if t in ref) / total)


def _token_flag(token: str, positive: str, negative: str) -> bool:
    """解析反射 token：出现否定标记优先判为 False。"""
    normalized = token.upper().replace(" ", "").replace("_", "")
    if negative.upper().replace(" ", "").replace("_", "") in normalized:
        return False
    return positive.upper().replace(" ", "").replace("_", "") in normalized


def _default_reflect(prompt: str) -> str:
    """默认反射器：按 `KIND|arg1|arg2` prompt 做规则判断。"""
    parts = prompt.split("|")
    kind = parts[0]
    if kind == "RETRIEVE":
        question = parts[1] if len(parts) > 1 else ""
        hit = any(keyword in question for keyword in _RETRIEVAL_KEYWORDS)
        return "[Retrieve]" if hit else "[No Retrieve]"
    if kind == "RELEVANT":
        question = parts[1] if len(parts) > 1 else ""
        context = parts[2] if len(parts) > 2 else ""
        return "[Relevant]" if _coverage(question, context) >= 0.12 else "[Irrelevant]"
    if kind == "SUPPORTED":
        sentence = parts[1] if len(parts) > 1 else ""
        contexts = parts[2] if len(parts) > 2 else ""
        return "[Supported]" if _coverage(sentence, contexts) >= 0.4 else "[Not Supported]"
    return "[Relevant]"


def _default_rewriter(question: str, contexts: list[Any]) -> str:
    """纠错重检索：把首条证据关键词追加到问题后，扩大召回面。"""
    head = _content(contexts[0])[:40] if contexts else ""
    return f"{question} {head}".strip()


def _default_decider(question: str, step: str, contexts: list[Any]) -> bool:
    """规划默认决策：已有足够上下文时跳过重复检索步骤。"""
    return len(contexts) < 6


def _merge_contexts(existing: list[Any], incoming: list[Any]) -> list[Any]:
    """按内容去重合并检索结果，保留原有顺序。"""
    seen = {_content(item) for item in existing}
    merged = list(existing)
    for item in incoming:
        content = _content(item)
        if content and content not in seen:
            seen.add(content)
            merged.append(item)
    return merged


@dataclass
class AdvancedRAGResult:
    """三种高级范式的统一输出。"""

    question: str
    answer: str
    contexts: list[Any]
    action: str
    groundedness: float = 0.0
    trace: list[str] = field(default_factory=list)
    reflection: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "context_count": len(self.contexts),
            "action": self.action,
            "groundedness": round(self.groundedness, 4),
            "trace": self.trace,
        }


class CorrectiveRAG:
    """基于 Groundedness 分数决定：原样返回 / 重新检索 / 丢弃答案。"""

    def __init__(
        self,
        retriever: Retriever | None = None,
        answerer: Answerer | None = None,
        *,
        threshold: float = 0.45,
        max_retries: int = 1,
        query_rewriter: Callable[[str, list[Any]], str] | None = None,
        groundedness_threshold: float = 0.3,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries 不能为负")
        self.retriever = retriever or _default_retriever
        self.answerer = answerer or _default_answerer
        self.threshold = threshold
        self.max_retries = max_retries
        self.query_rewriter = query_rewriter or _default_rewriter
        self.groundedness_threshold = groundedness_threshold

    def run(self, question: str) -> AdvancedRAGResult:
        trace: list[str] = []
        contexts = [_as_context(c) for c in self.retriever(question)]
        trace.append(f"retrieve:{len(contexts)}")
        for attempt in range(self.max_retries + 1):
            answer = str(self.answerer(question, contexts))
            score = GroundednessScorer(
                contexts, threshold=self.groundedness_threshold,
            ).score(answer).score
            trace.append(f"groundedness:{score:.3f}")
            if score >= self.threshold:
                return AdvancedRAGResult(question, answer, contexts, "return", score, trace)
            if attempt >= self.max_retries:
                return AdvancedRAGResult(
                    question, "依据不足，无法给出可靠答案。", contexts, "discard", score, trace,
                )
            rewritten = self.query_rewriter(question, contexts)
            contexts = [_as_context(c) for c in self.retriever(rewritten)]
            trace.append(f"re_retrieve:{len(contexts)}")
        raise AssertionError("unreachable")  # pragma: no cover


class SelfRAG:
    """反射 token 决策：是否检索 -> 是否相关 -> 是否支持。"""

    def __init__(
        self,
        retriever: Retriever | None = None,
        answerer: Answerer | None = None,
        reflector: ReflectionFn | None = None,
    ) -> None:
        self.retriever = retriever or _default_retriever
        self.answerer = answerer or _default_answerer
        self.reflector = reflector or _default_reflect

    def run(self, question: str) -> AdvancedRAGResult:
        trace: list[str] = []
        retrieve_token = self.reflector(f"RETRIEVE|{question}")
        should_retrieve = _token_flag(retrieve_token, "[RETRIEVE]", "[NORETRIEVE]")
        trace.append(f"retrieve_token:{retrieve_token}")
        contexts = list(self.retriever(question)) if should_retrieve else []

        relevant: list[bool] = []
        for context in contexts:
            token = self.reflector(f"RELEVANT|{question}|{_content(context)}")
            relevant.append(_token_flag(token, "[RELEVANT]", "[IRRELEVANT]"))
        kept = [c for c, flag in zip(contexts, relevant) if flag]
        trace.append(f"relevant:{sum(relevant)}/{len(relevant)}")

        answer = str(self.answerer(question, kept))
        joined = " ".join(_content(c) for c in kept)
        sentences = [s.strip() for s in _SENTENCE_RE.split(answer) if s.strip()]
        supported: list[bool] = []
        for sentence in sentences:
            token = self.reflector(f"SUPPORTED|{sentence}|{joined}")
            supported.append(_token_flag(token, "[SUPPORTED]", "[NOTSUPPORTED]"))
        trace.append(f"supported:{sum(supported)}/{len(supported)}")
        score = sum(supported) / len(supported) if supported else 0.0
        return AdvancedRAGResult(
            question, answer, kept,
            "retrieve" if should_retrieve else "no_retrieve",
            score, trace,
            {"retrieve": should_retrieve, "relevant": relevant, "supported": supported},
        )


class AgenticRAG:
    """规划式多步检索：先拆分步骤，再逐步决策是否检索并累积上下文。"""

    def __init__(
        self,
        planner: Planner | None = None,
        retriever: Retriever | None = None,
        answerer: Answerer | None = None,
        decider: Decider | None = None,
        *,
        max_steps: int = 4,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        self.planner = planner or QueryDecomposer().decompose
        self.retriever = retriever or _default_retriever
        self.answerer = answerer or _default_answerer
        self.decider = decider or _default_decider
        self.max_steps = max_steps

    def run(self, question: str) -> AdvancedRAGResult:
        steps = list(self.planner(question))[:self.max_steps]
        trace: list[str] = []
        contexts: list[Any] = []
        for step in steps:
            if not self.decider(question, step, contexts):
                trace.append(f"skip:{step}")
                continue
            found = list(self.retriever(step))
            contexts = _merge_contexts(contexts, found)
            trace.append(f"step:{step}->{len(found)}")
        answer = str(self.answerer(question, contexts))
        return AdvancedRAGResult(question, answer, contexts, "plan", 0.0, trace,
                                 {"steps": steps})


__all__ = [
    "AdvancedRAGResult", "CorrectiveRAG", "SelfRAG", "AgenticRAG",
]
