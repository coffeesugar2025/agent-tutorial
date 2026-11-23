"""引用质量与幻觉控制（RAG 高阶层）。

- ``CitationValidator``：校验答案中的 ``[1]`` / ``[source:doc]`` 引用能否在召回集中解析。
- ``GroundednessScorer``：逐句计算答案相对召回证据的词面 + 语义覆盖率。
- ``AnswerWithCitations``：带引用、支撑度与来源的结构化答案。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .embeddings import HashEmbeddings
from .hybrid import RetrievedChunk, bm25_tokenize

_INDEX_RE = re.compile(r"\[(\d+)\]")
_SOURCE_RE = re.compile(r"\[source:([^\]]+)\]", re.IGNORECASE)
_CN_SOURCE_RE = re.compile(r"\[来源[:：]([^\]]+)\]")
_SENTENCE_RE = re.compile(r"[。！？!?；;\n]+")


def _strip_citations(text: str) -> str:
    """评分前移除引用标记，避免标记本身被误判为未支撑句。"""
    text = _INDEX_RE.sub("", text or "")
    text = _SOURCE_RE.sub("", text)
    return _CN_SOURCE_RE.sub("", text)


# ---------------------------------------------------------------------------
# 证据归一化
# ---------------------------------------------------------------------------
@dataclass
class _Evidence:
    id: str
    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _as_evidence(item: Any, position: int) -> _Evidence:
    if isinstance(item, RetrievedChunk):
        return _Evidence(item.id, item.content,
                         str(item.metadata.get("source", item.doc_id)),
                         dict(item.metadata))
    data = dict(item)
    return _Evidence(
        str(data.get("id") or data.get("doc_id") or f"chunk-{position}"),
        str(data.get("content", "")),
        str(data.get("source") or data.get("id") or data.get("doc_id") or ""),
        dict(data.get("metadata") or {}),
    )


# ---------------------------------------------------------------------------
# 引用校验
# ---------------------------------------------------------------------------
@dataclass
class Citation:
    marker: str
    kind: str                 # "index" | "source"
    value: str
    valid: bool = False
    chunk_id: str | None = None
    reason: str = ""


@dataclass
class CitationReport:
    citations: list[Citation]
    valid: list[Citation]
    invalid: list[Citation]
    cited_chunk_ids: list[str]
    has_citations: bool
    is_valid: bool

    def invalid_markers(self) -> list[str]:
        return [c.marker for c in self.invalid]


class CitationValidator:
    """校验答案中的引用标记是否存在于召回集。"""

    def __init__(self, chunks: Iterable[RetrievedChunk | dict[str, Any]]) -> None:
        self.evidence = [_as_evidence(c, i) for i, c in enumerate(chunks)]

    def validate(self, answer: str) -> CitationReport:
        citations: list[Citation] = []
        for match in _INDEX_RE.finditer(answer or ""):
            index = int(match.group(1))
            target = self.evidence[index - 1] if 1 <= index <= len(self.evidence) else None
            citations.append(Citation(
                match.group(0), "index", str(index),
                valid=target is not None,
                chunk_id=target.id if target else None,
                reason="解析成功" if target else "序号超出召回集范围",
            ))
        for pattern in (_SOURCE_RE, _CN_SOURCE_RE):
            for match in pattern.finditer(answer or ""):
                value = match.group(1).strip()
                target = self._match_source(value)
                citations.append(Citation(
                    match.group(0), "source", value,
                    valid=target is not None,
                    chunk_id=target.id if target else None,
                    reason="解析成功" if target else "召回集中找不到该来源",
                ))
        # 按在答案中出现的先后顺序排列
        citations.sort(key=lambda c: (answer or "").find(c.marker))
        valid = [c for c in citations if c.valid]
        invalid = [c for c in citations if not c.valid]
        cited_ids: list[str] = []
        for c in valid:
            if c.chunk_id and c.chunk_id not in cited_ids:
                cited_ids.append(c.chunk_id)
        return CitationReport(
            citations=citations, valid=valid, invalid=invalid,
            cited_chunk_ids=cited_ids,
            has_citations=bool(citations),
            is_valid=bool(citations) and not invalid,
        )

    def _match_source(self, value: str) -> _Evidence | None:
        needle = value.lower()
        for item in self.evidence:
            candidates = [item.id, item.source, str(item.metadata.get("doc_id", ""))]
            if any(str(c).lower() == needle for c in candidates):
                return item
        for item in self.evidence:
            if needle in item.source.lower():
                return item
        return None


# ---------------------------------------------------------------------------
# 支撑度评分
# ---------------------------------------------------------------------------
@dataclass
class GroundednessReport:
    score: float
    sentence_scores: list[tuple[str, float]]
    supported: list[str]
    unsupported: list[str]
    threshold: float


class GroundednessScorer:
    """逐句计算答案被召回证据支撑的程度（0-1）。

    分数 = 0.7 * 词面覆盖率 + 0.3 * 哈希语义相似度（取各证据最大值）。
    """

    def __init__(self, chunks: Iterable[RetrievedChunk | dict[str, Any]] | None = None,
                 *, lexical_weight: float = 0.7, semantic_weight: float = 0.3,
                 threshold: float = 0.3) -> None:
        evidence = list(chunks or [])
        self.evidence = [_as_evidence(c, i) for i, c in enumerate(evidence)]
        self._embeddings = HashEmbeddings()
        self.lexical_weight = lexical_weight
        self.semantic_weight = semantic_weight
        self.threshold = threshold

    def lexical_coverage(self, sentence: str, evidence: str) -> float:
        query_tokens = bm25_tokenize(sentence)
        if not query_tokens:
            return 0.0
        evidence_tokens = set(bm25_tokenize(evidence))
        total = sum(len(t) for t in query_tokens) or 1
        hit = sum(len(t) for t in query_tokens if t in evidence_tokens)
        return min(1.0, hit / total)

    def semantic_similarity(self, sentence: str, evidence: str) -> float:
        vec_a = self._embeddings.embed_query(sentence)
        vec_b = self._embeddings.embed_query(evidence)
        return max(0.0, sum(a * b for a, b in zip(vec_a, vec_b)))

    def sentence_score(self, sentence: str) -> float:
        if not self.evidence:
            return 0.0
        best = 0.0
        for item in self.evidence:
            lexical = self.lexical_coverage(sentence, item.content)
            semantic = self.semantic_similarity(sentence, item.content)
            best = max(best, self.lexical_weight * lexical + self.semantic_weight * semantic)
        return min(1.0, best)

    def score(self, answer: str) -> GroundednessReport:
        sentences = [s.strip() for s in _SENTENCE_RE.split(_strip_citations(answer)) if s.strip()]
        if not sentences:
            return GroundednessReport(0.0, [], [], [], self.threshold)
        pairs = [(s, self.sentence_score(s)) for s in sentences]
        overall = sum(value for _, value in pairs) / len(pairs)
        return GroundednessReport(
            score=min(1.0, overall),
            sentence_scores=pairs,
            supported=[s for s, v in pairs if v >= self.threshold],
            unsupported=[s for s, v in pairs if v < self.threshold],
            threshold=self.threshold,
        )


# ---------------------------------------------------------------------------
# 结构化答案
# ---------------------------------------------------------------------------
@dataclass
class AnswerWithCitations:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    groundedness: float = 0.0
    is_grounded: bool = False
    citations_valid: bool = False
    unsupported_sentences: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        answer: str,
        chunks: Iterable[RetrievedChunk | dict[str, Any]],
        *,
        threshold: float = 0.3,
    ) -> "AnswerWithCitations":
        evidence = list(chunks)
        citation_report = CitationValidator(evidence).validate(answer)
        grounded = GroundednessScorer(evidence, threshold=threshold).score(answer)
        sources: list[str] = []
        for citation in citation_report.valid:
            for item in evidence:
                if _as_evidence(item, 0).id == citation.chunk_id:
                    source = str(_as_evidence(item, 0).source)
                    if source and source not in sources:
                        sources.append(source)
        return cls(
            answer=answer,
            citations=citation_report.citations,
            sources=sources,
            groundedness=grounded.score,
            is_grounded=not grounded.unsupported and grounded.score >= threshold,
            citations_valid=citation_report.is_valid,
            unsupported_sentences=grounded.unsupported,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [c.marker for c in self.citations if c.valid],
            "sources": self.sources,
            "groundedness": round(self.groundedness, 4),
            "is_grounded": self.is_grounded,
            "citations_valid": self.citations_valid,
            "unsupported_sentences": self.unsupported_sentences,
        }
