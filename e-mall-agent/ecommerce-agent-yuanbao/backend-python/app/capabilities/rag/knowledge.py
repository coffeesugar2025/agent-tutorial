"""知识图谱 / Ontology / Text2Cypher / GraphRAG / Neo4j 适配器契约。

高阶 RAG：把商品、类目、品牌、订单、券、售后政策建成三元组；
  Ontology     领域本体约束（实体类型、关系 domain/range），治理脏数据
  Text2Cypher  自然语言 → 受限 Cypher 模板（输出可执行 Cypher 文本）
  GraphRAG     种子实体 → 多跳子图 → 结构化上下文（补足向量检索缺失的关系推理）
  Neo4j       适配器契约：把本地图查询翻译成 Neo4j 可执行语句，生产替换存储
"""
from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.services import catalog


@dataclass(frozen=True)
class Triple:
    subject: str
    predicate: str
    obj: str


class Ontology:
    """本体约束：关系定义 domain/range，拒绝非法三元组。"""

    ENTITY_TYPES = ("Product", "Category", "Brand", "Order", "User", "Coupon", "Policy")
    RELATIONS: dict[str, tuple[str, str]] = {
        "属于类目": ("Product", "Category"),
        "品牌是": ("Product", "Brand"),
        "价格": ("Product", "Literal"),
        "库存": ("Product", "Literal"),
        "下单用户": ("Order", "User"),
        "包含商品": ("Order", "Product"),
        "适用类目": ("Coupon", "Category"),
        "关联政策": ("Category", "Policy"),
    }

    @staticmethod
    def type_of(entity: str) -> str:
        if entity.startswith("SKU-"):
            return "Product"
        if entity.startswith("EC"):
            return "Order"
        if entity.startswith("u_"):
            return "User"
        if entity.startswith("CAT-"):
            return "Category"
        if entity.startswith("C-"):
            return "Coupon"
        if entity.startswith("P-"):
            return "Policy"
        if entity.startswith("BR-"):
            return "Brand"
        return "Literal"

    def validate(self, t: Triple) -> dict[str, Any]:
        rule = self.RELATIONS.get(t.predicate)
        if not rule:
            return {"ok": False, "reason": f"未定义关系：{t.predicate}"}
        domain, rng = rule
        actual_s = self.type_of(t.subject)
        actual_o = "Literal" if self.type_of(t.obj) == "Literal" else self.type_of(t.obj)
        ok = (actual_s == domain or domain == "Literal") and (
            rng == "Literal" or actual_o == rng)
        return {"ok": ok, "domain": domain, "range": rng,
                "subject_type": actual_s, "object_type": actual_o}


class KnowledgeGraph:
    def __init__(self, ontology: Ontology | None = None) -> None:
        self.ontology = ontology or Ontology()
        self._triples: set[Triple] = set()
        self._adj: dict[str, list[tuple[str, str]]] = {}
        self._lock = threading.RLock()
        self.rejected: list[dict[str, Any]] = []

    def add(self, subject: str, predicate: str, obj: str) -> dict[str, Any]:
        t = Triple(subject, predicate, obj)
        check = self.ontology.validate(t)
        with self._lock:
            if not check["ok"]:
                self.rejected.append({"triple": [subject, predicate, obj], "check": check})
                return {"ok": False, **check}
            self._triples.add(t)
            self._adj.setdefault(subject, []).append((predicate, obj))
            self._adj.setdefault(obj, []).append(("<" + predicate, subject))
            return {"ok": True, "triple": [subject, predicate, obj]}

    def remove(self, subject: str, predicate: str, obj: str) -> bool:
        t = Triple(subject, predicate, obj)
        with self._lock:
            if t not in self._triples:
                return False
            self._triples.discard(t)
            return True

    def query(self, subject: str | None = None,
              predicate: str | None = None) -> list[dict[str, str]]:
        with self._lock:
            return [{"subject": t.subject, "predicate": t.predicate, "object": t.obj}
                    for t in sorted(self._triples, key=lambda x: (x.subject, x.predicate))
                    if (subject is None or t.subject == subject)
                    and (predicate is None or t.predicate == predicate)]

    def neighbors(self, entity: str) -> list[dict[str, str]]:
        with self._lock:
            return [{"relation": p, "entity": o} for p, o in self._adj.get(entity, [])]

    def subgraph(self, seed: str, hops: int = 2) -> dict[str, Any]:
        """BFS 多跳子图，返回节点、边与可注入 Prompt 的文本描述。"""
        with self._lock:
            seen: set[str] = set()
            edges: list[dict[str, str]] = []
            q: deque[tuple[str, int]] = deque([(seed, 0)])
            while q:
                node, d = q.popleft()
                if node in seen or d > hops:
                    continue
                seen.add(node)
                for rel, nxt in self._adj.get(node, []):
                    if rel.startswith("<"):
                        edges.append({"subject": nxt, "predicate": rel[1:], "object": node})
                    else:
                        edges.append({"subject": node, "predicate": rel, "object": nxt})
                    if nxt not in seen and d < hops:
                        q.append((nxt, d + 1))
        lines = [f"{e['subject']} —{e['predicate']}→ {e['object']}" for e in edges]
        return {"seed": seed, "hops": hops, "nodes": sorted(seen),
                "edges": edges, "text": "；".join(lines)}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"triples": len(self._triples), "nodes": len(self._adj),
                    "rejected": len(self.rejected)}


def sync_from_catalog(kg: KnowledgeGraph | None = None) -> KnowledgeGraph:
    """把领域数据同步成知识图谱（商品/类目/品牌/订单/券/政策）。"""
    g = kg or KnowledgeGraph()
    products = catalog.search_products(limit=20).get("products", [])
    for p in products:
        sku = p["sku"]
        g.add(sku, "属于类目", "CAT-" + str(p.get("category", "其他")))
        g.add(sku, "品牌是", "BR-" + str(p.get("brand", "其他")))
        g.add(sku, "价格", str(p.get("price", "")))
        g.add(sku, "库存", str(p.get("stock", "")))
    for c in catalog.list_coupons("u_1001").get("coupons", []):
        node = "C-" + str(c["code"])
        for cat in ("数码", "家居", "全品类"):
            if cat in str(c.get("title", "")) or c.get("category") == cat:
                g.add(node, "适用类目", "CAT-" + cat)
    for o in catalog.list_user_orders("u_1001", limit=5).get("orders", []):
        g.add(str(o["order_id"]), "下单用户", "u_1001")
    g.add("CAT-数码", "关联政策", "P-退货")
    g.add("CAT-家居", "关联政策", "P-退货")
    return g


KG = sync_from_catalog()


CYPHER_TEMPLATES: dict[str, str] = {
    "类目商品": "MATCH (p:Product)-[:属于类目]->(c:Category {{name:'{category}'}}) RETURN p.sku, p.name, p.price",
    "品牌商品": "MATCH (p:Product)-[:品牌是]->(b:Brand {{name:'{brand}'}}) RETURN p.sku, p.name, p.price",
    "用户订单": "MATCH (u:User {{id:'{user_id}'}})<-[:下单用户]-(o:Order) RETURN o.id, o.status, o.total",
    "券类目": "MATCH (c:Coupon)-[:适用类目]->(cat:Category) RETURN c.code, cat.name",
    "售后政策": "MATCH (cat:Category)-[:关联政策]->(pol:Policy) RETURN cat.name, pol.topic, pol.content",
}


def text2cypher(question: str) -> dict[str, Any]:
    """自然语言 → 受限 Cypher 模板（生成可执行语句文本，不是让模型自由发挥）。"""
    q = question
    cat = next((c for c in ("数码", "家居", "全品类") if c in q), "数码")
    brand = next((b for b in ("星野", "云眠", "清风", "北岸") if b in q), "星野")
    if any(k in q for k in ("订单", "买过", "我的")):
        key, params = "用户订单", {"user_id": "u_1001"}
    elif any(k in q for k in ("券", "优惠")):
        key, params = "券类目", {}
    elif any(k in q for k in ("政策", "退货", "保修")):
        key, params = "售后政策", {}
    elif any(k in q for k in ("品牌", "牌")):
        key, params = "品牌商品", {"brand": brand}
    else:
        key, params = "类目商品", {"category": cat}
    cypher = CYPHER_TEMPLATES[key].format(**params)
    return {"ok": True, "template": key, "params": params, "cypher": cypher,
            "guard": "仅 MATCH/RETURN，模板参数化，禁止任意 Cypher 执行"}


def graphrag_retrieve(question: str, kg: KnowledgeGraph | None = None,
                      hops: int = 2) -> dict[str, Any]:
    """GraphRAG：种子实体 → 多跳子图 → 结构化上下文段落。"""
    g = kg or KG
    seeds = []
    for sku in ("SKU-1001", "SKU-1002", "SKU-2002"):
        if sku in question:
            seeds.append(sku)
    if not seeds:
        b = next((b for b in ("星野", "云眠", "清风", "北岸") if b in question), None)
        if b:
            seeds.append("BR-" + b)
    if not seeds:
        cat = next((c for c in ("数码", "家居") if c in question), "数码")
        seeds.append("CAT-" + cat)
    subgraphs = [g.subgraph(s, hops) for s in seeds]
    passages = [{"text": f"子图[{sg['seed']}]：" + sg["text"],
                 "doc_id": "graph:" + sg["seed"], "chunk_id": "graph:" + sg["seed"],
                 "source": "graphrag", "nodes": sg["nodes"]}
                for sg in subgraphs if sg["text"]]
    return {"question": question, "seeds": seeds, "hops": hops,
            "subgraphs": subgraphs, "passages": passages,
            "cypher": text2cypher(question)}


NEO4J_ADAPTER = {
    "contract": "KnowledgeGraph.query / text2cypher → Neo4j Driver session.run",
    "config": ["NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"],
    "mapping": {"nodes": "Product/Category/Brand/Order/User/Coupon/Policy",
                "relations": list(Ontology.RELATIONS)},
    "note": "本地为进程内图；生产把 Cypher 交给 Neo4j，本体约束在写入侧复用",
}


def knowledge_spec() -> dict[str, Any]:
    return {
        "graph": "三元组 + 多跳 BFS 子图", "ontology": Ontology.RELATIONS,
        "text2cypher": "模板化受限生成，输出可执行 Cypher",
        "graphrag": "种子实体 → 子图 → 上下文段落",
        "neo4j": NEO4J_ADAPTER,
        "stats": KG.stats(),
    }
