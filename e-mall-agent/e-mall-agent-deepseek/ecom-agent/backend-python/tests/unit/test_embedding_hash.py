"""Hash Embedding 单元测试：确定性、归一化、相似度排序与单例管理。"""

from __future__ import annotations

import math

import pytest

from app.config import settings
from app.rag.embedding import HashEmbedding, build_embedding, get_embedding, reset_embedding

pytestmark = pytest.mark.unit


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def test_same_text_returns_identical_vector():
    embedding = HashEmbedding(128)

    first = embedding.embed_query("退货运费由谁承担")
    second = embedding.embed_query("退货运费由谁承担")
    batch = embedding.embed_documents(["退货运费由谁承担"])[0]

    assert first == second == batch
    assert len(first) == 128


def test_vector_is_l2_normalized():
    vector = HashEmbedding(64).embed_query("七天无理由退货政策说明")

    norm = math.sqrt(sum(value * value for value in vector))
    assert abs(norm - 1.0) < 1e-5
    assert any(value != 0 for value in vector)


def test_similar_text_scores_higher_than_unrelated():
    embedding = HashEmbedding(256)

    query = embedding.embed_query("退货运费由谁承担")
    similar = embedding.embed_query("退货运费谁承担")
    unrelated = embedding.embed_query("今天天气很好适合爬山")

    assert _dot(query, similar) > _dot(query, unrelated)
    assert _dot(query, similar) > 0


def test_empty_text_yields_zero_vector():
    vector = HashEmbedding(64).embed_query("")

    assert len(vector) == 64
    assert all(value == 0.0 for value in vector)


def test_build_embedding_hash_uses_configured_dimension():
    embedding = build_embedding("hash")

    assert embedding.provider == "hash"
    assert embedding.dim == settings.embedding_dim
    # 维度下限 64，避免过小的哈希桶导致冲突
    assert len(HashEmbedding(8).embed_query("测试")) == 64


def test_get_embedding_singleton_and_reset():
    first = get_embedding()
    second = get_embedding()
    reset_embedding()
    third = get_embedding()

    assert first is second
    assert third is not first
    assert first.provider == third.provider == "hash"
