"""稀疏检索单元测试：分词、hash id、BM25-lite 权重、点积/余弦与覆盖率。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：稀疏检索单元测试：分词、hash id、BM25-lite 权重、点积/余弦与覆盖率
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import math

import pytest

from app.rag.sparse import (
    HASH_SPACE,
    SparseEncoder,
    cosine,
    dot,
    normalize_sparse,
    overlap_score,
    sparse_vector,
    token_id,
    tokenize,
)

pytestmark = pytest.mark.unit


def test_tokenize_chinese_uses_bigram_and_single_chars():
    tokens = tokenize("退货运费")

    assert "退货" in tokens
    assert "运费" in tokens
    assert "退" in tokens  # 单字兜底，提升短 query 召回
    assert "" not in tokens


def test_tokenize_ascii_lowercases_and_keeps_words():
    tokens = tokenize("SKU-1001 iPhone16")

    assert "sku-1001" in tokens
    assert "iphone16" in tokens
    assert tokens == tokenize("sku-1001 IPHONE16")


def test_token_id_is_stable_and_in_range():
    first = token_id("退款")
    second = token_id("退款")

    assert first == second
    assert 0 <= first < HASH_SPACE
    assert token_id("退款") != token_id("运费")


def test_sparse_vector_is_normalized_and_non_empty():
    vector = sparse_vector("退款 退款 运费")
    norm = math.sqrt(sum(value * value for value in vector.values()))

    assert vector
    assert abs(norm - 1.0) < 1e-3
    assert sparse_vector("") == {}
    assert all(value > 0 for value in vector.values())


def test_dot_and_cosine_behave_as_expected():
    vector = sparse_vector("退货运费由谁承担")
    other = sparse_vector("退货运费谁承担")
    unrelated = sparse_vector("今天天气很好适合爬山")

    assert dot(vector, other) > dot(vector, unrelated)
    assert abs(cosine(vector, vector) - 1.0) < 1e-6
    assert cosine(vector, {}) == 0.0
    assert dot({}, other) == 0.0


def test_overlap_score_measures_keyword_coverage():
    assert overlap_score("退货运费", "退货运费由买家承担") == 1.0
    assert overlap_score("退货运费", "商品质量很好") == 0.0
    assert overlap_score("", "任意文本") == 0.0


def test_normalize_sparse_handles_zero_vector():
    assert normalize_sparse({}) == {}
    zero = {1: 0.0, 2: 0.0}
    assert normalize_sparse(zero) == zero


def test_sparse_encoder_wraps_document_and_query():
    encoder = SparseEncoder()

    documents = encoder.encode_documents(["退款政策", "物流查询"])
    query = encoder.encode_query("退款")

    assert len(documents) == 2
    assert all(isinstance(item, dict) and item for item in documents)
    assert dot(query, documents[0]) > dot(query, documents[1])
