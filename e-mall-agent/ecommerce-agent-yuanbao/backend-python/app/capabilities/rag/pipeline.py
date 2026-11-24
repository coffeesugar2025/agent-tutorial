"""端到端 RAG Pipeline：解析 → 切片 → 向量化 → 多路召回 → 重排 → Prompt 拼接 → 引用治理。

  ingest        文档入库（版本化 + 增量索引 + 向量/BM25 双写）
  query         5 种模式：vector / bm25 / hybrid / graph / sql / all
  answer        抽取式生成（不调用 LLM），事实只能来自召回段落，杜绝凭记忆补数
  citations     每个段落带 [n] 编号，回答事实附引用
  quality       覆盖率 / 可溯源 / 冲突检测 / 忠实度 / 幻觉控制
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.capabilities.context import TokenBudget, build_rag_prompt
from app.capabilities.rag.chunking import Chunk, DocumentStore, IncrementalIndex
from app.capabilities.rag.knowledge import KG, graphrag_retrieve
from app.capabilities.rag.text2sql import WAREHOUSE, run_text2sql
from app.capabilities.rag.vectorstore import (
    BM25Index, Hit, InMemoryVectorStore, hybrid_search, rerank,
)
from app.services import catalog


@dataclass
class RAGResult:
    question: str
    mode: str
    passages: list[dict[str, Any]]
    prompt: str
    citations: list[dict[str, Any]]
    answer: str
    quality: dict[str, Any]
    stages: list[str]
    elapsed_ms: int = 0
    guard: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "mode": self.mode,
                "passages": self.passages, "prompt": self.prompt,
                "citations": self.citations, "answer": self.answer,
                "quality": self.quality, "stages": self.stages,
                "elapsed_ms": self.elapsed_ms, "guard": self.guard}


def _default_documents() -> list[tuple[str, str, str]]:
    products = catalog.search_products(limit=10).get("products", [])
    product_lines = [
        f"商品 {p['sku']}「{p['name']}」属于{p['category']}类目，品牌{p['brand']}，"
        f"售价 ¥{p['price']:.2f}，库存 {p['stock']} 件，评分 {p['rating']}。"
        f"{p.get('description', '')}" for p in products
    ]
    policies = []
    for topic in ("退货", "换货", "保修", "发票", "价保"):
        d = catalog.get_after_sale_policy(topic)
        if d.get("ok"):
            policies.append(f"售后政策·{topic}：{d['content']}")
    coupons = catalog.list_coupons("u_1001").get("coupons", [])
    coupon_lines = [
        f"优惠券 {c['code']}「{c['title']}」门槛 ¥{c['threshold']:.2f}，"
        f"优惠 ¥{c['value']:.2f}，类型 {c['type']}。折扣券设封顶，满减券需达门槛。"
        for c in coupons
    ]
    orders = catalog.list_user_orders("u_1001", limit=5).get("orders", [])
    order_lines = [
        f"订单 {o['order_id']} 状态{o['status']}，实付 ¥{o['total']:.2f}，"
        f"下单时间 {o['created_at']}，物流节点 {o.get('logistics', {}).get('node', '')}。"
        for o in orders
    ]
    return [
        ("doc_products", "\n".join(product_lines), "txt"),
        ("doc_policies", "\n".join(policies), "txt"),
        ("doc_coupons", "\n".join(coupon_lines), "txt"),
        ("doc_orders", "\n".join(order_lines), "txt"),
    ]


class RAGPipeline:
    def __init__(self, auto_ingest: bool = True) -> None:
        self.docs = DocumentStore()
        self.index = IncrementalIndex(self.docs)
        self.vector = InMemoryVectorStore()
        self.bm25 = BM25Index()
        self.kg = KG
        self.warehouse = WAREHOUSE
        if auto_ingest:
            for doc_id, text, fmt in _default_documents():
                self.ingest(doc_id, text, fmt=fmt)

    def ingest(self, doc_id: str, text: str, fmt: str = "txt",
               strategy: str = "paragraph", chunk_size: int = 260,
               overlap: int = 30, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        res = self.docs.add(doc_id, text, fmt=fmt, strategy=strategy,
                            chunk_size=chunk_size, overlap=overlap, meta=meta)
        chunks = [Chunk(c["chunk_id"], c["doc_id"], c["version"], c["text"],
                        c["start"], c["end"], c["tokens"], c["meta"])
                  for c in res["chunks"]]
        diff = self.docs.diff(doc_id)
        self.vector.upsert(chunks)
        self.bm25.upsert(chunks)
        rec = self.index.apply(doc_id)
        return {"doc_id": doc_id, "version": res["version"],
                "chunks": len(chunks), "diff": diff, "index": rec}

    def update(self, doc_id: str, text: str, **kw: Any) -> dict[str, Any]:
        before = {c.chunk_id for c in self.docs.all_chunks() if c.doc_id == doc_id}
        res = self.docs.update(doc_id, text, **kw)
        after = {c.chunk_id for c in self.docs.all_chunks() if c.doc_id == doc_id}
        removed, added = before - after, after - before
        self.vector.delete(sorted(removed))
        self.bm25.delete(sorted(removed))
        new_chunks = [c for c in self.docs.all_chunks() if c.chunk_id in added]
        self.vector.upsert(new_chunks)
        self.bm25.upsert(new_chunks)
        self.index.apply(doc_id)
        return {**res, "indexed": {"added": sorted(added), "removed": sorted(removed)}}

    def delete(self, doc_id: str) -> dict[str, Any]:
        removed = [c.chunk_id for c in self.docs.all_chunks() if c.doc_id == doc_id]
        self.vector.delete(removed)
        self.bm25.delete(removed)
        self.index.remove(doc_id)
        return self.docs.delete(doc_id)

    def undo(self) -> dict[str, Any]:
        """撤销文档变更后重建双索引（保证向量/BM25 与文档仓库一致）。"""
        res = self.docs.undo()
        self.vector = InMemoryVectorStore()
        self.bm25 = BM25Index()
        self.vector.upsert(self.docs.all_chunks())
        self.bm25.upsert(self.docs.all_chunks())
        return {**res, "reindexed": self.stats()}

    # ------------------------------------------------------------ 检索
    def _text_passages(self, question: str, mode: str, top_k: int) -> list[dict[str, Any]]:
        if mode == "vector":
            hits = self.vector.search(question, top_k=top_k)
        elif mode == "bm25":
            hits = self.bm25.search(question, top_k=top_k)
        else:
            raw = hybrid_search(question, self.vector, self.bm25, top_k=top_k)
            hits = [Hit(h["chunk_id"], h["doc_id"], h["version"], h["text"],
                        h["score"], h["source"], h.get("meta", {}), h["rank"])
                    for h in raw["hits"]]
            hits = rerank(question, hits, top_k=top_k) if mode == "all" else hits
        return [{"text": h.text, "doc_id": h.doc_id, "chunk_id": h.chunk_id,
                 "source": h.source, "score": h.score} for h in hits]

    def query(self, question: str, mode: str = "all", top_k: int = 5,
              budget: TokenBudget | None = None) -> RAGResult:
        started = time.perf_counter()
        if mode not in ("vector", "bm25", "hybrid", "graph", "sql", "all"):
            raise ValueError("mode 必须是 vector/bm25/hybrid/graph/sql/all")
        stages: list[str] = []
        passages: list[dict[str, Any]] = []

        if mode in ("vector", "bm25", "hybrid", "all"):
            passages += self._text_passages(question, mode, top_k)
            stages.append(mode if mode != "all" else "hybrid+rrf+rerank")
        if mode == "graph":
            gr = graphrag_retrieve(question, self.kg, hops=2)
            passages += gr["passages"]
            stages += ["graph_seed", "subgraph_bfs", "text2cypher"]
        if mode == "sql":
            sql = run_text2sql(question, self.warehouse)
            passages.append({"text": f"Text2SQL 查询结果（{sql['template']}）：\n{sql['rows_as_text']}",
                             "doc_id": "sql:" + sql["template"],
                             "chunk_id": "sql:" + sql["template"],
                             "source": "text2sql", "score": 1.0})
            stages += ["text2sql", "sql_guard", "sqlite_execute"]
        if mode == "all":
            gr = graphrag_retrieve(question, self.kg, hops=1)
            passages += gr["passages"][:2]
            sql = run_text2sql(question, self.warehouse)
            passages.append({"text": f"结构化查询结果（{sql['template']}）：\n{sql['rows_as_text']}",
                             "doc_id": "sql:" + sql["template"],
                             "chunk_id": "sql:" + sql["template"],
                             "source": "text2sql", "score": 0.9})
            stages += ["graphrag", "text2sql"]

        # 去重 + 截断
        seen: set[str] = set()
        uniq = []
        for p in passages:
            if p["chunk_id"] not in seen:
                seen.add(p["chunk_id"])
                uniq.append(p)
        passages = uniq[: max(1, top_k + 2)]

        built = build_rag_prompt(question, passages, budget or TokenBudget())
        citations = built["citations"]
        answer = self._extractive_answer(question, passages, citations)
        quality = evaluate_citations(question, passages, citations, answer)
        return RAGResult(
            question=question, mode=mode, passages=passages, prompt=built["prompt"],
            citations=citations, answer=answer, quality=quality, stages=stages,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            guard={"hallucination_control": quality["hallucination_controlled"],
                   "refused": quality["refused"]},
        )

    @staticmethod
    def _extractive_answer(question: str, passages: list[dict[str, Any]],
                           citations: list[dict[str, Any]]) -> str:
        """抽取式回答：只拼接召回段落里与问题相关的句子，每个事实附 [n]。"""
        keys = set(re.findall(r"[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?", question))
        lines = []
        for i, p in enumerate(passages[: len(citations)], 1):
            sents = re.split(r"(?<=[。；\n])", p["text"])
            picked = [s.strip() for s in sents
                      if s.strip() and any(k in s for k in keys)]
            if not picked and sents:
                picked = [sents[0].strip()]
            if picked:
                lines.append(f"[{i}] " + " ".join(picked[:2])[:220])
        if not lines:
            return "资料不足：召回内容未覆盖该问题，无法给出有依据的回答（已启用幻觉控制）。"
        return "依据召回资料作答：\n" + "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        return {"documents": self.docs.stats(), "index": self.index.stats(),
                "vector": self.vector.stats(), "bm25": self.bm25.stats(),
                "graph": self.kg.stats(), "warehouse": self.warehouse.stats()}


PIPELINE = RAGPipeline()


def evaluate_citations(question: str, passages: list[dict[str, Any]],
                       citations: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    """引用质量评估：覆盖率 / 可溯源 / 冲突 / 忠实度 / 幻觉控制。"""
    traceable = sum(1 for c in citations if c.get("doc_id") and c.get("chunk_id"))
    coverage = round(traceable / max(1, len(passages)), 4)
    # 冲突检测：同一 SKU 在不同段落出现不同价格
    prices: dict[str, set[str]] = {}
    for p in passages:
        for sku, price in re.findall(r"(SKU-\d+)[^\d]{0,20}¥?\s?(\d+\.\d{2})", p["text"]):
            prices.setdefault(sku, set()).add(price)
    conflicts = [f"{sku} 出现矛盾价格 {sorted(v)}" for sku, v in prices.items() if len(v) > 1]
    # 忠实度：回答里的金额/数字必须能在召回段落里找到
    answer_nums = set(re.findall(r"\d+\.\d{2}|\b\d+\b", answer))
    passage_nums = set(re.findall(r"\d+\.\d{2}|\b\d+\b", " ".join(p["text"] for p in passages)))
    unsupported = sorted(n for n in answer_nums if n not in passage_nums and n not in {"1", "2", "3", "4", "5"})
    faithfulness = round(1 - len(unsupported) / max(1, len(answer_nums)), 4)
    refused = "资料不足" in answer
    return {
        "coverage": coverage,
        "traceable_citations": traceable,
        "total_passages": len(passages),
        "conflicts": conflicts,
        "unsupported_numbers": unsupported[:8],
        "faithfulness": faithfulness,
        "hallucination_controlled": True,
        "refused": refused,
        "quality_score": round(0.4 * coverage + 0.4 * faithfulness
                               + 0.2 * (0 if conflicts else 1), 4),
    }


def rag_spec() -> dict[str, Any]:
    return {
        "foundation": ["文档解析(txt/md/html)", "切片(fixed/paragraph/sentence)",
                       "HashEmbedding", "向量召回", "BM25 全文", "RRF 混合", "Rerank",
                       "带引用编号的 Prompt 拼接"],
        "advanced": ["版本管理", "增量索引 diff", "撤销 undo", "引用质量评估", "幻觉控制"],
        "expert": ["Text2SQL + SQL Guard", "Text2Cypher", "GraphRAG 多跳子图",
                   "知识图谱", "Ontology 本体约束", "Neo4j 适配器契约"],
        "vector_db_adapters": ["Milvus", "Qdrant", "Chroma", "FAISS", "Pinecone",
                               "Elasticsearch", "LlamaIndex"],
        "modes": ["vector", "bm25", "hybrid", "graph", "sql", "all"],
        "stats": PIPELINE.stats(),
    }
