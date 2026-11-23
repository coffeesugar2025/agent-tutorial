"""轻量知识图谱与 GraphRAG（RAG 高阶层）。

- ``KnowledgeGraph``：邻接表实现实体-关系-实体三元组的增删查、1-2 跳子图与路径。
- ``GraphRAGRetriever``：按规则从文档抽取「商品-类目 / 订单-商品 / 政策-关键词」
  三元组构图，并把子图转成可注入 prompt 的自然语言描述。

纯内存实现，接口预留替换为 Neo4j 等图数据库。
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from .ingest import Chunk

_CATEGORY_WORDS = ("数码", "家具", "家居", "服装", "食品", "办公")
_POLICY_KEYWORDS = ("退货", "退款", "配送", "包邮", "发票", "优惠", "质保", "运费")
_PRODUCT_RE = re.compile(r"([\u4e00-\u9fff]{2,10}?(?:耳机|椅|键盘|书桌|咖啡机|跑鞋|台灯|背包))")


# ---------------------------------------------------------------------------
# 图数据结构
# ---------------------------------------------------------------------------
@dataclass
class Entity:
    id: str
    type: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relation:
    source: str
    predicate: str
    target: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Subgraph:
    center: str
    hops: int
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


class KnowledgeGraph:
    """邻接表三元组存储。"""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._out: dict[str, list[Relation]] = {}
        self._in: dict[str, list[Relation]] = {}
        self._relations: dict[tuple[str, str, str], Relation] = {}

    def __len__(self) -> int:
        return len(self._entities)

    def add_entity(self, entity_id: str, type: str, name: str,
                   **attributes: Any) -> Entity:
        entity = Entity(entity_id, type, name, dict(attributes))
        self._entities[entity_id] = entity
        self._out.setdefault(entity_id, [])
        self._in.setdefault(entity_id, [])
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    def add_relation(self, source: str, predicate: str, target: str,
                     **attributes: Any) -> Relation:
        for entity_id, name in ((source, source), (target, target)):
            if entity_id not in self._entities:
                self.add_entity(entity_id, "Unknown", name)
        relation = Relation(source, predicate, target, dict(attributes))
        key = (source, predicate, target)
        self._relations[key] = relation
        if relation not in self._out[source]:
            self._out[source].append(relation)
        if relation not in self._in[target]:
            self._in[target].append(relation)
        return relation

    def remove_relation(self, source: str, predicate: str, target: str) -> bool:
        key = (source, predicate, target)
        relation = self._relations.pop(key, None)
        if relation is None:
            return False
        self._out.get(source, []).remove(relation)
        self._in.get(target, []).remove(relation)
        return True

    def remove_entity(self, entity_id: str) -> bool:
        if entity_id not in self._entities:
            return False
        for relation in list(self._out.get(entity_id, [])) + list(self._in.get(entity_id, [])):
            self.remove_relation(relation.source, relation.predicate, relation.target)
        self._entities.pop(entity_id, None)
        self._out.pop(entity_id, None)
        self._in.pop(entity_id, None)
        return True

    def neighbors(self, entity_id: str, *, direction: str = "both",
                  predicate: str | None = None) -> list[tuple[Relation, str]]:
        """返回 ``(关系, 邻居 id)``；direction 为 out/in/both。"""
        result: list[tuple[Relation, str]] = []
        if direction in ("out", "both"):
            result.extend((rel, rel.target) for rel in self._out.get(entity_id, [])
                          if predicate is None or rel.predicate == predicate)
        if direction in ("in", "both"):
            result.extend((rel, rel.source) for rel in self._in.get(entity_id, [])
                          if predicate is None or rel.predicate == predicate)
        return result

    def subgraph(self, entity_id: str, hops: int = 1,
                 max_nodes: int = 50) -> Subgraph:
        """以 entity_id 为中心做广度优先的 1-2 跳子图检索。"""
        if entity_id not in self._entities or hops < 1:
            return Subgraph(entity_id, hops)
        order = [entity_id]
        visited = {entity_id}
        relations: dict[tuple[str, str, str], Relation] = {}
        frontier = [entity_id]
        for _ in range(hops):
            next_frontier: list[str] = []
            for node in frontier:
                for relation, neighbor in self.neighbors(node):
                    relations[(relation.source, relation.predicate, relation.target)] = relation
                    if neighbor not in visited:
                        visited.add(neighbor)
                        order.append(neighbor)
                        next_frontier.append(neighbor)
            frontier = next_frontier
            if len(visited) >= max_nodes:
                break
        return Subgraph(
            center=entity_id, hops=hops,
            entities=[self._entities[eid] for eid in order],
            relations=[relations[key] for key in sorted(relations)],
        )

    def path(self, source: str, target: str, max_hops: int = 3) -> list[str] | None:
        """无向最短路径（返回实体 id 列表），不存在返回 None。"""
        if source not in self._entities or target not in self._entities:
            return None
        if source == target:
            return [source]
        queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
        seen = {source}
        while queue:
            node, route = queue.popleft()
            if len(route) - 1 >= max_hops:
                continue
            for _, neighbor in self.neighbors(node):
                if neighbor in seen:
                    continue
                candidate = route + [neighbor]
                if neighbor == target:
                    return candidate
                seen.add(neighbor)
                queue.append((neighbor, candidate))
        return None

    def describe_subgraph(self, subgraph: Subgraph) -> str:
        """把子图转成可注入 prompt 的自然语言描述。"""
        if not subgraph.entities:
            return "知识库中未找到相关实体。"
        center = self._entities.get(subgraph.center)
        center_name = center.name if center else subgraph.center
        lines = [f"以「{center_name}」为中心的 {subgraph.hops} 跳知识子图："]
        entities = "、".join(
            f"{entity.name}（{entity.type}）" for entity in subgraph.entities
        )
        lines.append(f"相关实体：{entities}。")
        if subgraph.relations:
            lines.append("关系：" + "；".join(
                f"{self._entities[r.source].name} --{r.predicate}--> "
                f"{self._entities[r.target].name}"
                for r in subgraph.relations
            ) + "。")
        else:
            lines.append("该实体暂无直接关系。")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# GraphRAG 检索器
# ---------------------------------------------------------------------------
@dataclass
class GraphContext:
    entity_id: str
    hops: int
    description: str
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    def as_context(self) -> str:
        return self.description


class GraphRAGRetriever:
    """规则抽取建图 + 子图自然语言化。"""

    def __init__(self, graph: KnowledgeGraph | None = None) -> None:
        self.graph = graph or KnowledgeGraph()
        self._doc_index: dict[str, str] = {}  # 名称 -> 实体 id（便于按名检索）

    @staticmethod
    def _text_and_meta(doc: Chunk | dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if isinstance(doc, Chunk):
            return doc.content, {**doc.metadata, "doc_id": doc.doc_id}
        data = dict(doc)
        return str(data.get("content", "")), dict(data.get("metadata") or {
            "source": data.get("source", ""), "category": data.get("category", "")
        })

    def _register(self, entity_id: str, name: str) -> None:
        self._doc_index.setdefault(name.lower(), entity_id)

    def build(self, documents: Iterable[Chunk | dict[str, Any]]) -> KnowledgeGraph:
        """按规则从文档抽取三元组，重复构建幂等（实体按 id 覆盖）。"""
        for index, doc in enumerate(documents):
            text, meta = self._text_and_meta(doc)
            doc_id = str(meta.get("doc_id") or meta.get("id") or f"doc-{index}")
            doc_entity = f"doc:{doc_id}"
            source = str(meta.get("source") or doc_id)
            self.graph.add_entity(doc_entity, "Document", source,
                                  doc_id=doc_id, content=text[:200])
            self._register(doc_entity, source)

            # 规则一：商品 - 类目
            category = next((word for word in _CATEGORY_WORDS if word in text), None)
            if meta.get("category") == "product" and category is None:
                category = str(meta.get("category"))
            products = set(_PRODUCT_RE.findall(text))
            products.update(re.findall(r"(P\d{3,4})", text.upper()))
            if meta.get("product"):
                products.add(str(meta["product"]))
            for product in sorted(products):
                product_entity = f"product:{product}"
                self.graph.add_entity(product_entity, "Product", product)
                self._register(product_entity, product)
                self.graph.add_relation(product_entity, "EVIDENCED_BY", doc_entity)
                if category:
                    category_entity = f"category:{category}"
                    self.graph.add_entity(category_entity, "Category", category)
                    self._register(category_entity, category)
                    self.graph.add_relation(product_entity, "BELONGS_TO", category_entity)

            # 规则二：订单 - 商品
            order_ids = re.findall(r"(O\d{3,4})", text.upper())
            for order_id in order_ids:
                order_entity = f"order:{order_id}"
                self.graph.add_entity(order_entity, "Order", order_id)
                self._register(order_entity, order_id)
                self.graph.add_relation(order_entity, "EVIDENCED_BY", doc_entity)
                for product_id in re.findall(r"(P\d{3,4})", text.upper()):
                    product_entity = f"product:{product_id}"
                    self.graph.add_entity(product_entity, "Product", product_id)
                    self.graph.add_relation(order_entity, "CONTAINS", product_entity)

            # 规则三：政策 - 关键词
            if meta.get("category") == "policy" or "政策" in source or "规则" in source:
                policy_entity = f"policy:{doc_id}"
                self.graph.add_entity(policy_entity, "Policy", source)
                self._register(policy_entity, source)
                self.graph.add_relation(policy_entity, "EVIDENCED_BY", doc_entity)
                for keyword in _POLICY_KEYWORDS:
                    if keyword in text:
                        keyword_entity = f"keyword:{keyword}"
                        self.graph.add_entity(keyword_entity, "Keyword", keyword)
                        self._register(keyword_entity, keyword)
                        self.graph.add_relation(policy_entity, "MENTIONS", keyword_entity)
        return self.graph

    def _resolve(self, query: str) -> str | None:
        if query in self.graph._entities:
            return query
        needle = (query or "").lower()
        if needle in self._doc_index:
            return self._doc_index[needle]
        matches = [entity_id for name, entity_id in self._doc_index.items()
                   if needle and needle in name]
        return sorted(matches)[0] if matches else None

    def retrieve(self, query: str, hops: int = 1) -> GraphContext:
        """按实体 id 或名称查子图；未命中返回空描述（不编造事实）。"""
        entity_id = self._resolve(query)
        if entity_id is None:
            return GraphContext(query, hops, "知识图谱中未找到相关实体。")
        subgraph = self.graph.subgraph(entity_id, hops=hops)
        return GraphContext(
            entity_id=entity_id, hops=hops,
            description=self.graph.describe_subgraph(subgraph),
            entities=subgraph.entities, relations=subgraph.relations,
        )
