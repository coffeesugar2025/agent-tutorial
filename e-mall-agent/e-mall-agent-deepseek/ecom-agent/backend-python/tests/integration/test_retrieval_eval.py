"""集成测试：知识入库 → 混合检索 → 检索指标 / 上下文组装。

全部离线：``MOCK_LLM=true``、``EMBEDDING_PROVIDER=hash``、``VECTOR_STORE=memory``、
``DATABASE_URL=sqlite:///./test.db``（见 ``tests/conftest.py``）。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：集成测试：知识入库 → 混合检索 → 检索指标 / 上下文组装
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio

import pytest

from app.infra.db import session_scope
from app.infra.models import KnowledgeChunk, KnowledgeDocument
from app.rag.assembler import assemble
from app.rag.eval import evaluate_retrieval, ndcg_at_k, recall_at_k, report_to_dict
from app.rag.ingest import ingest_document, ingest_text
from app.rag.retriever import hybrid_search
from app.rag.store import keyword_search_chunks

pytestmark = pytest.mark.integration

DOC_TITLE = "退款与退货运费政策（集成测试）"
DOC_TEXT = (
    "一、七天无理由退货的退货运费由买家承担。\n\n"
    "二、商品存在质量问题时运费由商家承担。\n\n"
    "三、退款审核通过后 1-3 个工作日内原路退回。\n\n"
    "四、生鲜商品不支持七天无理由退货，质量问题可在 24 小时内申请。"
)
QUERY = "退货运费由谁承担"


def _ingest() -> dict[str, object]:
    result = ingest_text(DOC_TITLE, DOC_TEXT, doc_type="POLICY")
    assert result.get("ok") is True, result
    return result


def _document_chunks(document_id: int) -> list[int]:
    with session_scope() as db:
        rows = db.query(KnowledgeChunk.id).filter(KnowledgeChunk.document_id == document_id).all()
    return [int(row[0]) for row in rows]


def test_ingest_text_creates_chunks_and_memory_vectors():
    result = _ingest()

    assert result["chunkCount"] >= 1
    assert result["store"] == "memory"
    document_id = int(result["documentId"])
    with session_scope() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        assert document.status == "READY"
        assert document.chunk_count == result["chunkCount"]
    assert len(_document_chunks(document_id)) == result["chunkCount"]


def test_reingest_same_document_is_idempotent():
    result = _ingest()
    document_id = int(result["documentId"])

    again = ingest_document(document_id, content=DOC_TEXT)

    assert again["ok"] is True
    assert again.get("skipped") is True
    assert again["chunkCount"] == result["chunkCount"]


def test_hybrid_search_returns_relevant_chunk():
    result = _ingest()
    document_id = int(result["documentId"])

    search = asyncio.run(hybrid_search(QUERY, top_k=3))

    assert search.items, search.debug
    assert search.items[0].document_id == document_id
    assert "退货运费" in search.items[0].content or "运费" in search.items[0].content
    assert search.debug["store"] == "memory"
    assert search.debug["latencyMs"] >= 0
    assert all(item.chunk_id in _document_chunks(document_id) for item in search.items)


def test_retrieval_metrics_on_real_hits():
    _ingest()
    search = asyncio.run(hybrid_search(QUERY, top_k=3))

    retrieved = [item.chunk_id for item in search.items]
    relevant = {retrieved[0]}

    assert recall_at_k(retrieved, relevant, 1) == 1.0
    assert ndcg_at_k(retrieved, relevant, 3) == 1.0

    report = evaluate_retrieval(
        [{"query": QUERY, "retrieved": retrieved, "relevant": sorted(relevant)}],
        ks=(1, 3),
    )
    payload = report_to_dict(report)

    assert report.cases == 1
    assert report.recall_at_k[1] == 1.0
    assert report.mrr == 1.0
    assert payload["recallAtK"]["1"] == 1.0


def test_evaluate_retrieval_synthetic_cases():
    cases = [
        {"query": "q1", "retrieved": [1, 2, 3], "relevant": [1]},
        {"query": "q2", "retrieved": [3, 2, 1], "relevant": [1]},
    ]
    report = evaluate_retrieval(cases, ks=(1, 3))

    assert report.cases == 2
    assert report.recall_at_k[3] == 1.0
    assert report.recall_at_k[1] == 0.5
    assert report.ndcg_at_k[1] == 0.5
    assert report.mrr == pytest.approx(round((1.0 + 1 / 3) / 2, 4))
    assert report.details[0]["mrr"] == 1.0
    assert report_to_dict(report)["ndcgAtK"]["3"] == 0.75


def test_assemble_context_has_citations_within_budget():
    _ingest()
    search = asyncio.run(hybrid_search(QUERY, top_k=3))

    context = assemble(search.items, token_budget=600, query=QUERY)

    assert context.item_count >= 1
    assert context.citations
    assert context.citations[0]["chunkId"] == search.items[0].chunk_id
    assert context.text
    assert "untrusted_data" in context.text
    assert context.token_used <= 600


def test_keyword_fallback_reads_indexed_chunks():
    _ingest()

    hits = keyword_search_chunks(QUERY, top_k=3, visibility="PUBLIC")

    assert hits
    assert all(hit.source == "keyword" for hit in hits)
    assert any("运费" in hit.content for hit in hits)
    assert len(hits) <= 3
