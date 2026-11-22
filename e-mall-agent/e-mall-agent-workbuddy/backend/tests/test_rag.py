"""RAG 测试：确定性向量、检索召回、上下文格式化。"""
from app.rag.embeddings import HashEmbeddings, tokenize
from app.rag.pipeline import RAGPipeline


def test_hash_embeddings_are_deterministic():
    emb = HashEmbeddings(dimension=64)
    a = emb.embed_query("七天无理由退货政策")
    b = emb.embed_query("七天无理由退货政策")
    assert a == b
    assert len(a) == 64
    assert abs(sum(v * v for v in a) - 1.0) < 1e-6


def test_tokenize_handles_chinese_bigrams():
    tokens = tokenize("退货政策 refund")
    assert "退货" in tokens
    assert "退款" not in tokens
    assert "refund" in tokens


def test_retrieve_policy_doc():
    pipeline = RAGPipeline(top_k=2)
    results = pipeline.retrieve("我想知道退货政策")
    assert results
    assert results[0]["source"] == "售后政策"
    assert "退货" in results[0]["content"]


def test_as_context_contains_source():
    pipeline = RAGPipeline()
    context = pipeline.as_context("发票怎么开")
    assert "支付与发票" in context
