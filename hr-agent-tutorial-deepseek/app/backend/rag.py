"""制度知识库：切片 + BM25 + 哈希向量 + RRF 融合。

为什么不用现成向量库？
- 教程要离线可跑、确定性、可解释。哈希向量虽然语义能力弱，但没有外部依赖，
  每次启动得到完全相同的索引，适合做回归评测。
- 真正决定“答案对不对”的往往是版本治理：active / archived / draft 与生效日期。
  所以检索前先做元数据过滤，再谈相关性。

引用约束：``search()`` 返回的每个命中都带着原始片段 ``snippet``，
Agent 只能引用这里出现过的片段，不能自己编造文档编号。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime

try:  # 作为包导入
    from . import config
except ImportError:  # python app/backend/main.py
    import config  # type: ignore[no-redef]

from common.data import all_policy_documents
from common.text import chunk_text

CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
ASCII_RE = re.compile(r"[a-z0-9][a-z0-9+.#]*")
SNIPPET_MAX = 320


def tokenize(text: str) -> list[str]:
    """中文按字符 bigram，英文/数字按词切分。

    中文不引入分词库：bigram 对“年假”“结转”“司龄”这类 HR 术语足够稳，
    而且完全确定。英文统一小写，``P6-1`` 会切成 ``p6`` 和 ``1``。
    """
    lowered = (text or "").lower()
    tokens: list[str] = []
    for match in ASCII_RE.finditer(lowered):
        tokens.append(match.group())
    for run in CJK_RE.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _clip(text: str, limit: int = SNIPPET_MAX) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "……"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class KnowledgeBase:
    """制度知识库索引，进程内构建一次，只读。"""

    EMBED_DIM = 256
    RRF_K = 60

    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = documents if documents is not None else all_policy_documents()
        self.chunks: list[dict] = []
        self._postings: dict[str, dict[int, int]] = defaultdict(dict)
        self._doc_lengths: list[int] = []
        self._vectors: list[dict[int, float]] = []
        self._df: Counter[str] = Counter()
        self._avgdl = 0.0
        self._build()

    # ------------------------------------------------------------------
    # 建索引
    # ------------------------------------------------------------------
    def _build(self) -> None:
        for document in self.documents:
            for heading, body in self._sections(document.get("content", "")):
                for piece in chunk_text(body, chunk_size=420, overlap=60):
                    text = piece.strip()
                    if not text:
                        continue
                    self.chunks.append(
                        {
                            "doc_id": document["doc_id"],
                            "title": document["title"],
                            "version": document["version"],
                            "status": document["status"],
                            "effective_from": document.get("effective_from"),
                            "effective_to": document.get("effective_to"),
                            "category": document.get("category", ""),
                            "tags": document.get("tags", []),
                            "heading": heading,
                            "text": text,
                            "chunk_index": len(self.chunks),
                        }
                    )
        self._doc_lengths = []
        self._vectors = []
        for index, chunk in enumerate(self.chunks):
            tokens = tokenize(chunk["heading"] + "\n" + chunk["text"])
            counts = Counter(tokens)
            for token, tf in counts.items():
                self._postings[token][index] = tf
                self._df[token] += 1
            self._doc_lengths.append(max(len(tokens), 1))
            self._vectors.append(self._embed(tokens))
        self._avgdl = (
            sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0.0
        )

    @staticmethod
    def _sections(markdown: str) -> list[tuple[str, str]]:
        """按 ``##`` / ``###`` 标题切段，保留 h3 作为引用里的“条第”。

        返回 ``(heading, body)``；第一个标题前的文档信息单独成段。
        """
        lines = (markdown or "").replace("\r\n", "\n").splitlines()
        sections: list[tuple[str, str]] = []
        buffer: list[str] = []
        heading = "文档信息"
        h2 = ""
        h3 = ""

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body:
                sections.append((heading, body))
            buffer.clear()

        for line in lines:
            if line.startswith("# "):
                flush()
                h2 = h3 = ""
                heading = "文档信息"
            elif line.startswith("### "):
                flush()
                h3 = line[4:].strip()
                heading = h3
            elif line.startswith("## "):
                flush()
                h2 = line[3:].strip()
                h3 = ""
                heading = h2
            else:
                buffer.append(line)
        flush()
        return sections

    # ------------------------------------------------------------------
    # 向量
    # ------------------------------------------------------------------
    @classmethod
    def _embed(cls, tokens: list[str]) -> dict[int, float]:
        raw: dict[int, float] = defaultdict(float)
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "little") % cls.EMBED_DIM
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            raw[slot] += sign
        norm = math.sqrt(sum(value * value for value in raw.values())) or 1.0
        return {slot: value / norm for slot, value in raw.items()}

    @staticmethod
    def _cosine(left: dict[int, float], right: dict[int, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(slot, 0.0) for slot, value in left.items())

    # ------------------------------------------------------------------
    # 版本 / 状态过滤
    # ------------------------------------------------------------------
    @staticmethod
    def _is_visible(
        chunk: dict,
        *,
        include_archived: bool,
        include_drafts: bool,
        today: date,
    ) -> bool:
        status = chunk["status"]
        if status == "archived":
            return include_archived
        if status == "draft":
            if not include_drafts:
                return False
        elif status != "active":
            return False
        if status == "active":
            start = _parse_date(chunk.get("effective_from"))
            end = _parse_date(chunk.get("effective_to"))
            if start and start > today:
                return False
            if end and end < today:
                return False
        return True

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def _bm25(self, query_tokens: list[str]) -> list[float]:
        total = len(self.chunks)
        scores = [0.0] * total
        if total == 0 or self._avgdl <= 0:
            return scores
        k1, b = 1.5, 0.75
        query_counts = Counter(query_tokens)
        for token, qf in query_counts.items():
            postings = self._postings.get(token)
            if not postings:
                continue
            df = self._df[token]
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            weight = min(qf, 3)
            for index, tf in postings.items():
                length = self._doc_lengths[index]
                denominator = tf + k1 * (1 - b + b * length / self._avgdl)
                scores[index] += idf * tf * (k1 + 1) / denominator * weight
        return scores

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        include_archived: bool = False,
        include_drafts: bool = False,
        today: date | None = None,
    ) -> list[dict]:
        query = (query or "").strip()
        if not query or not self.chunks:
            return []
        today = today or date.today()
        candidates = [
            index
            for index, chunk in enumerate(self.chunks)
            if self._is_visible(
                chunk,
                include_archived=include_archived,
                include_drafts=include_drafts,
                today=today,
            )
        ]
        if not candidates:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        bm25 = self._bm25(query_tokens)
        query_vector = self._embed(query_tokens)
        cosine = [self._cosine(query_vector, vector) for vector in self._vectors]

        best_bm25 = max(bm25[index] for index in candidates)
        best_cosine = max(cosine[index] for index in candidates)
        # 证据门槛：既没有词面匹配、向量也很弱，就认定“制度库没有依据”。
        if best_bm25 < 1.0 and best_cosine < 0.30:
            return []

        limit = max(20, top_k * 4)
        by_bm25 = sorted(candidates, key=lambda index: bm25[index], reverse=True)[:limit]
        by_vector = sorted(candidates, key=lambda index: cosine[index], reverse=True)[:limit]
        fused: dict[int, float] = defaultdict(float)
        for rank, index in enumerate(by_bm25):
            fused[index] += 1.0 / (self.RRF_K + rank + 1)
        for rank, index in enumerate(by_vector):
            fused[index] += 1.0 / (self.RRF_K + rank + 1)

        ranked = sorted(
            fused,
            key=lambda index: (fused[index], bm25[index], cosine[index]),
            reverse=True,
        )

        metadata_query = any(
            keyword in query for keyword in ("版本", "生效日期", "文档编号", "替代", "解释部门")
        )
        results: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for index in ranked:
            chunk = self.chunks[index]
            # 文档信息块只放编号与生效日期，不适合当答案引用；
            # 只有用户明确问版本 / 生效日期时才允许它进入候选。
            if chunk["heading"] == "文档信息" and not metadata_query:
                continue
            key = (chunk["doc_id"], chunk["heading"])
            if key in seen:
                continue
            seen.add(key)
            bm25_norm = bm25[index] / (bm25[index] + 2.5)
            confidence = 0.65 * bm25_norm + 0.35 * max(cosine[index], 0.0)
            score = round(min(0.97, 0.42 + 0.55 * confidence), 3)
            results.append(
                {
                    "doc_id": chunk["doc_id"],
                    "title": chunk["title"],
                    "version": chunk["version"],
                    "heading": chunk["heading"],
                    "snippet": _clip(chunk["text"]),
                    "score": score,
                    "status": chunk["status"],
                    "_chunk_index": index,
                }
            )
            if len(results) >= top_k:
                break
        # RRF 决定候选集，最终展示按混合置信度排序，保证前端看到的 score 单调递减。
        results.sort(key=lambda item: (-item["score"], item["doc_id"], item["heading"]))
        return results

    # ------------------------------------------------------------------
    # 引用校验与统计
    # ------------------------------------------------------------------
    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    def grounded(self, citation: dict) -> bool:
        """引用必须能对应到一个真实召回片段（doc_id + heading + snippet 前缀）。"""
        snippet = (citation.get("snippet") or "").rstrip("……").strip()
        for chunk in self.chunks:
            if (
                chunk["doc_id"] == citation.get("doc_id")
                and chunk["heading"] == citation.get("heading")
                and chunk["text"].startswith(snippet[:80])
            ):
                return True
        return False

    def all_citations_grounded(self, citations: list[dict]) -> bool:
        return bool(citations) and all(self.grounded(citation) for citation in citations)
