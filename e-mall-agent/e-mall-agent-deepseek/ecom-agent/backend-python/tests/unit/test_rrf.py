"""RRF 融合单元测试：倒数排名打分、去重保序与空输入。"""

from __future__ import annotations

import pytest

from app.rag.retriever import RRF_K, reciprocal_rank_fusion, rrf_fuse
from app.rag.store import Hit

pytestmark = pytest.mark.unit


def _hit(doc_id: int, title: str = "") -> Hit:
    return Hit(
        id=doc_id,
        score=0.5,
        content=f"content-{doc_id}",
        payload={"chunk_id": doc_id, "title": title or f"doc-{doc_id}"},
    )


def test_reciprocal_rank_fusion_scores_first_places_highest():
    scores = reciprocal_rank_fusion([[1, 2, 3], [1, 2, 3]], k=60)

    assert scores[1] > scores[2] > scores[3]
    assert scores[1] == pytest.approx(2 * (1.0 / (60 + 1)))


def test_reciprocal_rank_fusion_uses_configured_k():
    default_scores = reciprocal_rank_fusion([[1]], k=RRF_K)
    small_k_scores = reciprocal_rank_fusion([[1]], k=1)

    assert default_scores[1] == pytest.approx(1.0 / (RRF_K + 1))
    assert small_k_scores[1] > default_scores[1]


def test_rrf_fuse_dedupes_and_sorts_desc():
    dense = [_hit(1), _hit(2)]
    sparse = [_hit(2), _hit(3)]

    fused = rrf_fuse(dense, sparse, k=60)
    ids = [hit.id for hit, _ in fused]

    assert sorted(ids) == [1, 2, 3]
    assert len(ids) == len(set(ids))
    assert ids[0] == 2  # 两路都召回，RRF 分数最高
    assert [score for _, score in fused] == sorted(
        (score for _, score in fused), reverse=True
    )


def test_rrf_fuse_prefers_dense_hit_payload():
    dense = [_hit(1, title="dense-title")]
    sparse = [_hit(1, title="sparse-title")]

    fused = rrf_fuse(dense, sparse)
    hit, _ = fused[0]

    assert hit.payload["title"] == "dense-title"
    assert hit.score == 0.5


def test_rrf_fuse_handles_empty_inputs():
    assert rrf_fuse([], []) == []
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[], []]) == {}


def test_rrf_fuse_single_route_preserves_relevance_order():
    fused = rrf_fuse([], [_hit(7), _hit(8)])

    assert [hit.id for hit, _ in fused] == [7, 8]
    assert fused[0][1] > fused[1][1]
