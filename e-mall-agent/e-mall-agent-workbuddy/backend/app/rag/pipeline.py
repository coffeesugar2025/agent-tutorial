"""RAG pipeline: seeded knowledge base -> embeddings -> in-memory vector store."""
from __future__ import annotations

from typing import Any

from langchain_core.vectorstores import InMemoryVectorStore

from ..config import get_settings
from .embeddings import HashEmbeddings, tokenize

SEED_DOCS: list[dict[str, str]] = [
    {"source": "售后政策", "category": "policy", "content":
     "七天无理由退货：签收后 7 天内，商品保持完好可申请退货。退款在仓库签收后 1-3 个工作日原路退回。"},
    {"source": "售后政策", "category": "policy", "content":
     "质保规则：数码类商品整机保修 12 个月，人为损坏不在保修范围；家具类商品保修 36 个月。"},
    {"source": "配送规则", "category": "logistics", "content":
     "配送时效：一线城市 1-2 天，其他地区 2-4 天。满 199 元包邮，未满收取 12 元运费。"},
    {"source": "配送规则", "category": "logistics", "content":
     "发货时间：现货订单在付款后 24 小时内发出；预售商品以商品页标注时间为准。"},
    {"source": "优惠规则", "category": "promotion", "content":
     "优惠券：新用户首单立减 30 元；会员订单满 500 减 50。同一订单只能使用一张优惠券。"},
    {"source": "支付与发票", "category": "payment", "content":
     "发票：支持电子普通发票与增值税专用发票，订单完成后在订单详情页申请，1-2 个工作日开具。"},
    {"source": "商品知识", "category": "product", "content":
     "无线降噪耳机 Pro：40 小时续航，主动降噪，支持蓝牙 5.3 与多点连接，适合通勤与办公。"},
    {"source": "商品知识", "category": "product", "content":
     "人体工学椅：网布透气、腰托可调、扶手多向调节，建议久坐办公用户选择。"},
]


class RAGPipeline:
    def __init__(self, top_k: int | None = None) -> None:
        self.top_k = top_k or get_settings().rag_top_k
        self.store = InMemoryVectorStore(HashEmbeddings())
        # 配置 ECOM_MILVUS_URL 时切换到 Milvus（不可用时适配器自动回退内存向量库）
        try:
            from ..infra.milvus_store import MilvusVectorStore
            from ..infra.settings import InfraSettings

            settings = InfraSettings.from_env()
            if settings.milvus_url:
                candidate = MilvusVectorStore(settings=settings)
                if candidate.status()["active"]:
                    self.store = candidate  # type: ignore[assignment]
        except Exception:
            pass
        self.ingest()

    def ingest(self, docs: list[dict[str, str]] | None = None) -> int:
        docs = docs if docs is not None else SEED_DOCS
        if not docs:
            return 0
        self.store.add_texts(
            [d["content"] for d in docs],
            metadatas=[{"source": d["source"], "category": d["category"]} for d in docs],
        )
        return len(docs)

    def retrieve(self, query: str, top_k: int | None = None,
                 category: str | None = None) -> list[dict[str, Any]]:
        """Hybrid ranking: hashed-vector recall + deterministic lexical overlap.

        Pure vector recall over hashed n-grams is noisy for short Chinese queries,
        so a token-overlap score is applied on top of the vector store results.
        """
        k = top_k or self.top_k
        query_tokens = {t for t in tokenize(query or "") if len(t) >= 2}
        documents = self.store.similarity_search(query or " ", k=max(k * 3, len(SEED_DOCS)))
        ranked: list[tuple[float, int, dict[str, Any]]] = []
        for index, doc in enumerate(documents):
            meta = doc.metadata or {}
            if category and meta.get("category") != category:
                continue
            doc_tokens = set(tokenize(doc.page_content))
            overlap = sum(len(t) for t in query_tokens & doc_tokens)
            source_bonus = 4 if any(t in str(meta.get("source", "")) for t in query_tokens) else 0
            ranked.append((overlap + source_bonus, -index, {
                "content": doc.page_content,
                "source": meta.get("source", "知识库"),
                "category": meta.get("category", "general"),
                "score": float(overlap + source_bonus),
            }))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        results = [item[2] for item in ranked[:k]]
        # Deterministic fallback so an empty query still returns useful context.
        if not results and category is None:
            for doc in SEED_DOCS[:k]:
                results.append({**doc, "score": 0.0})
        return results

    def as_context(self, query: str, top_k: int | None = None) -> str:
        return "\n".join(f"[{r['source']}] {r['content']}" for r in self.retrieve(query, top_k))


_pipeline: RAGPipeline | None = None


def get_rag_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RAGPipeline()
    return _pipeline


def reset_rag_pipeline() -> RAGPipeline:
    global _pipeline
    _pipeline = RAGPipeline()
    return _pipeline
