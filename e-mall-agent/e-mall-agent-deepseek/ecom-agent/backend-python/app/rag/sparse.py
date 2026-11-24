"""稀疏向量：本地 BM25-lite（token → hash id → 权重）。

为什么需要稀疏：中文短 query 的关键词命中（如"退货运费"）常被 dense 向量稀释，
BM25 类稀疏召回能显著提升政策类问答的召回率；两者用 RRF 融合。

实现要点：
* token 化：中文按 **字 bigram** + 单字兜底，英文/数字按词；
* hash id：``blake2b`` 稳定哈希到 ``[0, 2^31)``，与 Milvus SPARSE_FLOAT_VECTOR 兼容；
* 权重：``(1 + ln(tf)) * 长度启发式`` 近似 IDF（无全局语料统计，避免引入索引状态）。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-12] 检索增强 RAG
# 职责：稀疏向量：本地 BM25-lite（token → hash id → 权重）
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
ASCII_RE = re.compile(r"[a-z0-9][a-z0-9_\-.]*")
PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
HASH_SPACE = 2**31 - 1


def tokenize(text: str) -> list[str]:
    """中英混合分词：中文 bigram（含单字兜底）+ 英文词。"""
    if not text:
        return []
    lowered = text.lower()
    tokens: list[str] = []
    for word in ASCII_RE.findall(lowered):
        if len(word) >= 1:
            tokens.append(word)
    cjk_runs = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]+", lowered)
    for run in cjk_runs:
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        # 单字也保留一份，提升短 query 召回
        tokens.extend(list(run))
    return tokens


def token_id(token: str) -> int:
    """稳定 hash id（跨进程一致，不依赖 PYTHONHASHSEED）。"""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % HASH_SPACE


def term_weight(token: str, tf: int) -> float:
    """BM25-lite 权重：次线性 tf + 词长启发式（长词更稀有）。"""
    sublinear = 1 + math.log(tf) if tf > 0 else 0.0
    length_boost = 1 + min(len(token), 8) / 20.0
    return round(sublinear * length_boost, 6)


def sparse_vector(text: str) -> dict[int, float]:
    """文本 → 稀疏向量 ``{hash_id: weight}``（已 L2 归一化）。"""
    tokens = tokenize(text)
    if not tokens:
        return {}
    counts = Counter(tokens)
    vector: dict[int, float] = {}
    for token, tf in counts.items():
        index = token_id(token)
        weight = term_weight(token, tf)
        vector[index] = round(vector.get(index, 0.0) + weight, 6)
    return normalize_sparse(vector)


def normalize_sparse(vector: dict[int, float]) -> dict[int, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm <= 0:
        return vector
    return {index: round(value / norm, 6) for index, value in vector.items()}


def dot(a: dict[int, float], b: dict[int, float]) -> float:
    """稀疏点积（取较小字典遍历，O(min(|a|,|b|))）。"""
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(index, 0.0) for index, value in a.items())


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    """归一化向量的点积即余弦相似度。"""
    return round(dot(a, b), 6)


def overlap_score(query: str, text: str) -> float:
    """关键词覆盖率（0~1），用于 FULLTEXT 降级路径的重排。"""
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return 0.0
    text_tokens = set(tokenize(text))
    return round(len(query_tokens & text_tokens) / len(query_tokens), 4)


class SparseEncoder:
    """稀疏编码器（可替换为服务端 BM25，接口保持一致）。"""

    def encode_documents(self, texts: list[str]) -> list[dict[int, float]]:
        return [sparse_vector(text) for text in texts]

    def encode_query(self, text: str) -> dict[int, float]:
        return sparse_vector(text)


encoder = SparseEncoder()

__all__ = [
    "HASH_SPACE",
    "SparseEncoder",
    "cosine",
    "dot",
    "encoder",
    "normalize_sparse",
    "overlap_score",
    "sparse_vector",
    "token_id",
    "tokenize",
]
