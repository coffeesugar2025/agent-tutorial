"""RAG 基础层 / 进阶层 / 高阶层专项测试。

覆盖文档解析与三种切片策略、BM25 + RRF 混合检索与重排、知识治理（版本/
增量/回滚/撤销/租户隔离）、引用与支撑度、Text2SQL/Cypher、轻量知识图谱。
所有实现均为离线内存版本，不依赖外部服务。
"""
from __future__ import annotations

import json

import pytest

from app.rag.citation import (
    AnswerWithCitations,
    CitationValidator,
    GroundednessScorer,
)
from app.rag.governance import KnowledgeAudit, VersionedStore
from app.rag.graphrag import GraphRAGRetriever, KnowledgeGraph
from app.rag.hybrid import (
    BM25Index,
    HybridRetriever,
    RetrievedChunk,
    Reranker,
)
from app.rag.ingest import Chunk, Chunker, Document, parse_json, parse_markdown, parse_text
from app.rag.text2sql import Text2Cypher, Text2SQL


DOCS = [
    {"id": "a", "content": "七天无理由退货：签收后7天内可退货，退款1-3个工作日原路退回。",
     "metadata": {"source": "售后政策", "category": "policy"}},
    {"id": "b", "content": "配送时效：一线城市1-2天，满199元包邮，未满收取12元运费。",
     "metadata": {"source": "配送规则", "category": "logistics"}},
    {"id": "c", "content": "无线降噪耳机 Pro：40小时续航，主动降噪，支持蓝牙5.3。",
     "metadata": {"source": "商品知识", "category": "product"}},
]


# ---------------------------------------------------------------------------
# 一、文档解析与切片（基础层）
# ---------------------------------------------------------------------------
def test_parse_text_returns_single_section():
    sections = parse_text("  纯文本内容  ")
    assert len(sections) == 1
    assert sections[0].content == "纯文本内容"
    assert parse_text("   ") == []


def test_parse_markdown_splits_by_heading_level():
    sections = parse_markdown("# 标题一\n内容甲\n\n## 标题二\n内容乙", source="手册")
    assert len(sections) == 2
    assert sections[0].metadata["heading"] == "标题一"
    assert sections[1].metadata["heading"] == "标题一 > 标题二"
    assert sections[1].metadata["level"] == 2
    assert "标题二" in sections[1].content


def test_parse_json_splits_by_record():
    raw = json.dumps(
        [{"title": "耳机", "content": "主动降噪"}, {"title": "椅子", "content": "腰托可调"}],
        ensure_ascii=False,
    )
    sections = parse_json(raw)
    assert len(sections) == 2
    assert sections[0].metadata["record_index"] == 0
    assert "耳机" in sections[0].content
    assert sections[1].metadata["record"]["title"] == "椅子"


def test_chunker_fixed_length_with_overlap():
    doc = Document("d1", "一二三四五六七八九十" * 2, "text")
    chunks = Chunker("fixed", chunk_size=8, overlap=2).chunk(doc)
    assert len(chunks) >= 3
    assert all(len(chunk.content) <= 8 for chunk in chunks)
    assert chunks[0].content[-2:] == chunks[1].content[:2]


def test_chunker_section_strategy_keeps_heading_metadata():
    md = "# 标题一\n内容甲\n\n## 标题二\n内容乙"
    chunks = Chunker("section", chunk_size=100).chunk(Document("md", md, "markdown"))
    assert len(chunks) == 2
    assert chunks[0].metadata["heading"] == "标题一"
    assert chunks[1].metadata["level"] == 2
    assert chunks[0].metadata["strategy"] == "section"


def test_chunker_paragraph_strategy_groups_paragraphs():
    text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
    chunks = Chunker("paragraph", chunk_size=12).chunk(Document("d", text, "text"))
    assert len(chunks) >= 2
    assert all("段内容" in chunk.content for chunk in chunks)


def test_chunk_dataclass_fields_and_stable_ids():
    chunk = Chunk("c1", "d1", "内容", {"source": "政策"}, 3)
    rebuilt = Chunk("c1", "d1", "内容", {"source": "政策"}, 3)
    assert (chunk.id, chunk.doc_id, chunk.content, chunk.metadata, chunk.position) == (
        rebuilt.id, rebuilt.doc_id, rebuilt.content, rebuilt.metadata, rebuilt.position,
    )
    generated = Chunker("fixed", chunk_size=10).chunk(Document("d2", "测试内容", "text"))
    assert generated[0].id == Chunker("fixed", chunk_size=10).chunk(
        Document("d2", "测试内容", "text"))[0].id


def test_unsupported_chunk_strategy_is_rejected():
    with pytest.raises(ValueError):
        Chunker("unknown")


# ---------------------------------------------------------------------------
# 二、混合检索（进阶层）
# ---------------------------------------------------------------------------
def test_bm25_chinese_recall_with_bigrams():
    index = BM25Index()
    index.add(
        ["七天无理由退货，签收后7天内可退货，退款原路退回", "配送时效满199元包邮"],
        ids=["a", "b"],
    )
    hits = index.search("退货政策")
    assert hits and hits[0].doc_id == "a"
    assert hits[0].score > 0


def test_bm25_returns_empty_for_no_term_match():
    index = BM25Index()
    index.add(["退货政策说明"], ids=["a"])
    assert index.search("量子力学黑洞") == []


def test_rrf_fusion_score_and_source_details():
    retriever = HybridRetriever(DOCS)
    results = retriever.search("退货政策")
    assert results
    top = results[0]
    assert top.doc_id == "a"
    assert "bm25" in top.sources and "fused" in top.sources
    assert top.sources["fused"].rank == 1
    assert abs(top.score - top.sources["fused"].contribution) < 1e-9


def test_rrf_channel_weights_change_results():
    retriever = HybridRetriever(DOCS)
    # 「退货政策」的向量相似度低于阈值，仅 BM25 通道有效
    bm25_only = retriever.search("退货政策", weights=(0.0, 1.0))
    vector_only = retriever.search("退货政策", weights=(1.0, 0.0))
    assert bm25_only and bm25_only[0].doc_id == "a"
    assert vector_only == []


def test_reranker_improves_lexically_best_chunk():
    candidates = [
        RetrievedChunk("a", "a", "配送时效与运费说明，满199包邮，一线城市1-2天。",
                       {"source": "配送规则"}, score=0.9, rank=1),
        RetrievedChunk("b", "b", "七天无理由退货政策，退款1-3个工作日原路退回。",
                       {"source": "售后政策"}, score=0.5, rank=2),
    ]
    reranked = Reranker("退货政策").rerank(candidates)
    assert reranked[0].doc_id == "b"
    assert reranked[0].score > reranked[1].score
    assert "rerank" in reranked[0].sources
    assert candidates[0].doc_id == "a"  # 不修改输入


def test_hybrid_empty_index_returns_empty():
    assert HybridRetriever().search("退货") == []


def test_hybrid_unrelated_query_returns_empty_not_fallback():
    retriever = HybridRetriever(DOCS)
    assert retriever.search("量子力学与黑洞蒸发") == []


def test_hybrid_category_filter():
    retriever = HybridRetriever(DOCS)
    assert retriever.search("退货政策", category="logistics") == []
    results = retriever.search("满199包邮", category="logistics")
    assert results and all(chunk.metadata["category"] == "logistics" for chunk in results)


# ---------------------------------------------------------------------------
# 三、知识治理（高阶层）
# ---------------------------------------------------------------------------
def _chunks(*contents: str) -> list[Chunk]:
    return [Chunk(f"c{i}", "doc", text, {}, i) for i, text in enumerate(contents)]


def test_versioned_store_keeps_old_versions():
    store = VersionedStore()
    first = store.ingest("doc", _chunks("内容一"))
    second = store.ingest("doc", _chunks("内容二"))
    assert (first.version, second.version) == (1, 2)
    assert len(store.versions("doc")) == 2
    assert store.get_version("doc", 1).chunks[0].content == "内容一"
    assert store.current_version("doc") == 2


def test_incremental_indexing_skips_unchanged_chunks():
    store = VersionedStore()
    store.ingest("doc", [Chunk("c1", "doc", "AAA", {}, 0), Chunk("c2", "doc", "BBB", {}, 1)])
    version = store.ingest("doc", [Chunk("c1", "doc", "AAA", {}, 0),
                                   Chunk("c3", "doc", "CCC", {}, 2)])
    assert version.indexed == 1
    assert version.unchanged == 1
    assert {chunk.content for chunk in store.active_chunks("doc")} == {"AAA", "CCC"}


def test_rollback_to_previous_version():
    store = VersionedStore()
    store.ingest("doc", _chunks("第一版"))
    store.ingest("doc", _chunks("第二版"))
    target = store.rollback("doc", 1)
    assert target is not None and target.version == 1
    assert store.current_version("doc") == 1
    assert [chunk.content for chunk in store.active_chunks("doc")] == ["第一版"]
    assert store.get_version("doc", 2).revoked


def test_revoke_version_falls_back_to_previous():
    store = VersionedStore()
    store.ingest("doc", _chunks("保留版"))
    store.ingest("doc", _chunks("撤销版"))
    assert store.revoke("doc", 2) is True
    assert store.revoke("doc", 2) is False
    assert store.current_version("doc") == 1
    assert [chunk.content for chunk in store.active_chunks("doc")] == ["保留版"]


def test_tenant_isolation():
    store = VersionedStore()
    store.ingest("doc", _chunks("租户A"), tenant="tenant-a", category="policy")
    store.ingest("doc", _chunks("租户B"), tenant="tenant-b", category="product")
    assert [c.content for c in store.active_chunks("doc", tenant="tenant-a")] == ["租户A"]
    assert [c.content for c in store.active_chunks("doc", tenant="tenant-b")] == ["租户B"]
    assert store.active_chunks("doc", tenant="missing") == []
    assert store.active_chunks("doc", tenant="tenant-b", category="policy") == []


def test_knowledge_audit_records_all_actions():
    audit = KnowledgeAudit()
    store = VersionedStore(audit=audit)
    store.ingest("doc", _chunks("一"))
    store.ingest("doc", _chunks("二"))
    store.revoke("doc", 2)
    store.rollback("doc", 1)
    assert [entry.action for entry in audit.query()] == [
        "ingest", "update", "revoke", "rollback",
    ]
    assert len(audit.query(doc_id="doc", tenant="default")) == 4


# ---------------------------------------------------------------------------
# 四、引用质量与幻觉控制（高阶层）
# ---------------------------------------------------------------------------
EVIDENCE = [
    {"id": "e1", "source": "售后政策",
     "content": "七天无理由退货：签收后7天内可申请退货，退款1-3个工作日原路退回。"},
    {"id": "e2", "source": "配送规则", "content": "配送时效：满199元包邮。"},
]


def test_citation_valid_markers_are_resolved():
    answer = "七天无理由退货，7天内可申请。[1] [source:配送规则]"
    report = CitationValidator(EVIDENCE).validate(answer)
    assert report.is_valid and report.has_citations
    assert len(report.valid) == 2
    assert report.invalid == []
    assert report.cited_chunk_ids == ["e1", "e2"]


def test_citation_invalid_markers_are_flagged():
    answer = "火星政策规定如此。[9] [source:火星政策]"
    report = CitationValidator(EVIDENCE).validate(answer)
    assert not report.is_valid
    assert report.invalid_markers() == ["[9]", "[source:火星政策]"]
    assert report.cited_chunk_ids == []


def test_groundedness_score_distinguishes_supported_and_hallucinated():
    scorer = GroundednessScorer(EVIDENCE)
    grounded = "七天无理由退货，签收后7天内可申请退货，退款1-3个工作日原路退回。"
    hallucinated = "木星即将变成恒星，导致全球气温骤降五十度。"
    high = scorer.score(grounded)
    low = scorer.score(hallucinated)
    assert 0.0 <= low.score < high.score <= 1.0
    assert high.score >= 0.6 and high.unsupported == []
    assert any("木星" in sentence for sentence in low.unsupported)


def test_answer_with_citations_structure():
    answer = "七天无理由退货，7天内可申请退货。[1]"
    result = AnswerWithCitations.build(answer, EVIDENCE)
    payload = result.to_dict()
    assert payload["citations"] == ["[1]"]
    assert payload["sources"] == ["售后政策"]
    assert payload["citations_valid"] is True
    assert payload["is_grounded"] is True
    assert payload["groundedness"] >= 0.3


# ---------------------------------------------------------------------------
# 五、Text2SQL / Text2Cypher
# ---------------------------------------------------------------------------
def test_text2sql_generates_and_executes_query():
    engine = Text2SQL()
    result = engine.run("数码类商品")
    assert result.sql.startswith("SELECT")
    assert "LIMIT" in result.sql
    assert result.rows
    assert all(row["category"] == "数码" for row in result.as_dicts())


def test_text2sql_parses_record_id_and_custom_limit():
    engine = Text2SQL()
    result = engine.run("前3个商品")
    assert result.sql.endswith("LIMIT 3")
    assert len(result.rows) == 3
    order = engine.run("订单O1001包含哪些商品")
    assert order.params == ("O1001",) and len(order.rows) == 2


def test_text2sql_auto_adds_limit():
    engine = Text2SQL()
    result = engine.execute("SELECT id FROM products")
    assert result.sql.endswith("LIMIT 20")
    assert len(result.rows) == 8


@pytest.mark.parametrize("malicious_sql", [
    "DROP TABLE products",
    "SELECT * FROM products; DELETE FROM orders",
    "SELECT * FROM secrets",
    "SELECT id FROM products WHERE 1=1 UNION SELECT * FROM orders",
    "SELECT id FROM products; -- 注入",
    "UPDATE products SET price = 0",
])
def test_text2sql_rejects_injection(malicious_sql):
    engine = Text2SQL()
    assert engine.validate(malicious_sql) is False
    with pytest.raises(ValueError):
        engine.execute(malicious_sql)
    assert engine.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 8


def test_text2cypher_emits_template_without_executing():
    generator = Text2Cypher()
    query = generator.generate("订单O1001包含哪些商品")
    assert "MATCH" in query.cypher
    assert query.params["id"] == "O1001"
    assert query.pattern == "order_products"
    with pytest.raises(NotImplementedError):
        generator.execute(query)


# ---------------------------------------------------------------------------
# 六、轻量知识图谱
# ---------------------------------------------------------------------------
def _sample_graph() -> KnowledgeGraph:
    graph = KnowledgeGraph()
    graph.add_entity("p", "Product", "耳机")
    graph.add_entity("c", "Category", "数码")
    graph.add_entity("o", "Order", "O1001")
    graph.add_relation("p", "BELONGS_TO", "c")
    graph.add_relation("o", "CONTAINS", "p")
    return graph


def test_knowledge_graph_triple_crud():
    graph = _sample_graph()
    assert len(graph) == 3
    assert graph.get_entity("p").name == "耳机"
    assert [neighbor for _, neighbor in graph.neighbors("o")] == ["p"]
    assert graph.remove_relation("p", "BELONGS_TO", "c") is True
    assert graph.remove_relation("p", "BELONGS_TO", "c") is False
    assert graph.remove_entity("o") is True
    assert graph.get_entity("o") is None


def test_graph_subgraph_one_and_two_hops():
    graph = _sample_graph()
    one = graph.subgraph("o", hops=1)
    two = graph.subgraph("o", hops=2)
    assert {entity.name for entity in one.entities} == {"O1001", "耳机"}
    assert "数码" in {entity.name for entity in two.entities}
    assert len(two.relations) > len(one.relations)


def test_graph_path_query():
    graph = _sample_graph()
    assert graph.path("o", "c") == ["o", "p", "c"]
    assert graph.path("o", "unknown") is None


def test_graphrag_builds_graph_and_retrieves_subgraph():
    documents = [
        {"content": "无线降噪耳机 Pro 属于数码类目，40小时续航",
         "metadata": {"source": "商品知识", "category": "product"}},
        {"content": "订单 O1001 包含商品 P001", "metadata": {"source": "订单数据"}},
        {"content": "七天无理由退货，退款原路退回",
         "metadata": {"source": "售后政策", "category": "policy"}},
    ]
    retriever = GraphRAGRetriever()
    graph = retriever.build(documents)
    assert len(graph) >= 8
    one_hop = retriever.retrieve("O1001", hops=1)
    two_hop = retriever.retrieve("O1001", hops=2)
    assert "O1001" in one_hop.description
    assert one_hop.entities and two_hop.entities
    assert retriever.retrieve("不存在的实体").description == "知识图谱中未找到相关实体。"
