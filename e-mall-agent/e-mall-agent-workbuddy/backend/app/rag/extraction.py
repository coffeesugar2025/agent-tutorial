"""知识抽取流水线：实体 / 关系 / 事件三阶段，规则 + 可注入 LLM 函数。

- ``EntityExtractor``：商品、订单、类目、政策关键词、金额等实体。
- ``RelationExtractor``：属于 / 包含 / 支持等关系。
- ``EventExtractor``：退货、退款、配送等事件及时间、金额、条件参数。
- ``extract_knowledge``：统一编排，返回 :class:`KnowledgeGraphDraft`。

所有规则均为离线确定性实现；传入 ``llm`` 可替换为真实模型输出。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .graphrag import KnowledgeGraph

LLMExtract = Callable[[str], list[Any]]

_PRODUCT_RE = re.compile(r"([\u4e00-\u9fff]{2,10}?(?:耳机|椅|键盘|书桌|咖啡机|跑鞋|台灯|背包))")
_PRODUCT_CODE_RE = re.compile(r"(P\d{3,4})", re.IGNORECASE)
_ORDER_CODE_RE = re.compile(r"(O\d{3,4})", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*元")
_DURATION_RE = re.compile(r"\d+\s*(?:个)?\s*(?:工作日|天|小时|个月|年)")
_CONDITION_RE = re.compile(r"(?:签收后|付款后|订单完成后|满)\s*\d*\s*(?:天|元|小时|个月)?")
_CLAUSE_RE = re.compile(r"[。！？!?；;，,、\n]+")
_BELONGS_RE = re.compile(r"([^\s，。；、]{2,12}?)\s*属于\s*([^\s，。；、]{2,10})")
_SUPPORTS_RE = re.compile(r"([^\s，。；、]{2,12}?)\s*支持\s*([^\s，。；、]{2,12})")

_CATEGORIES = ("数码", "家具", "家居", "服装", "食品", "办公")
_POLICY_KEYWORDS = ("退货", "退款", "配送", "包邮", "发票", "优惠", "质保", "运费")
_EVENT_TYPES = {
    "退货": "ReturnEvent", "退款": "RefundEvent", "配送": "DeliveryEvent",
    "发货": "ShipmentEvent", "开票": "InvoiceEvent", "优惠": "PromotionEvent",
}
_METHODS = ("原路退回", "包邮", "电子普通发票", "增值税专用发票", "多点连接", "主动降噪")


@dataclass
class ExtractedEntity:
    id: str
    type: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "name": self.name,
                "attributes": dict(self.attributes)}


@dataclass
class ExtractedRelation:
    source: str
    predicate: str
    target: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "predicate": self.predicate,
                "target": self.target, "attributes": dict(self.attributes)}


@dataclass
class ExtractedEvent:
    id: str
    trigger: str
    type: str
    arguments: dict[str, str] = field(default_factory=dict)
    participants: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "trigger": self.trigger, "type": self.type,
                "arguments": dict(self.arguments), "participants": list(self.participants)}


@dataclass
class KnowledgeGraphDraft:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    events: list[ExtractedEvent] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entities": [e.as_dict() for e in self.entities],
            "relations": [r.as_dict() for r in self.relations],
            "events": [e.as_dict() for e in self.events],
        }

    def to_graph(self) -> KnowledgeGraph:
        """转换为现有 ``KnowledgeGraph``，事件也作为实体入图。"""
        graph = KnowledgeGraph()
        for entity in self.entities:
            graph.add_entity(entity.id, entity.type, entity.name, **entity.attributes)
        name_to_id = {entity.name: entity.id for entity in self.entities}
        for relation in self.relations:
            source = name_to_id.get(relation.source, relation.source)
            target = name_to_id.get(relation.target, relation.target)
            graph.add_relation(source, relation.predicate, target, **relation.attributes)
        for event in self.events:
            graph.add_entity(event.id, "Event", event.trigger, **event.arguments)
            for participant in event.participants:
                pid = name_to_id.get(participant, participant)
                graph.add_relation(pid, "PARTICIPATED_IN", event.id)
        return graph


def _coerce_entities(items: Iterable[Any]) -> list[ExtractedEntity]:
    result: list[ExtractedEntity] = []
    for item in items:
        if isinstance(item, ExtractedEntity):
            result.append(item)
            continue
        data = dict(item)
        result.append(ExtractedEntity(
            str(data.get("id", "")), str(data.get("type", "Unknown")),
            str(data.get("name", "")), dict(data.get("attributes") or {}),
        ))
    return [e for e in result if e.id and e.name]


def _dedupe_entities(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    seen: set[str] = set()
    result: list[ExtractedEntity] = []
    for entity in entities:
        if entity.id not in seen:
            seen.add(entity.id)
            result.append(entity)
    return result


class EntityExtractor:
    """规则抽取实体；``llm`` 注入后优先使用模型返回的实体列表。"""

    def __init__(self, llm: LLMExtract | None = None) -> None:
        self.llm = llm

    def extract(self, text: str) -> list[ExtractedEntity]:
        if self.llm is not None:
            return _dedupe_entities(_coerce_entities(self.llm(text)))
        return _dedupe_entities(self._rule_extract(text))

    def _rule_extract(self, text: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        for name in _PRODUCT_RE.findall(text):
            entities.append(ExtractedEntity(f"product:{name}", "Product", name))
        for code in _PRODUCT_CODE_RE.findall(text.upper()):
            entities.append(ExtractedEntity(f"product:{code}", "Product", code))
        for code in _ORDER_CODE_RE.findall(text.upper()):
            entities.append(ExtractedEntity(f"order:{code}", "Order", code))
        for word in _CATEGORIES:
            if word in text:
                entities.append(ExtractedEntity(f"category:{word}", "Category", word))
        for word in _POLICY_KEYWORDS:
            if word in text:
                entities.append(ExtractedEntity(f"keyword:{word}", "Keyword", word))
        for number in _AMOUNT_RE.findall(text):
            name = f"{number}元"
            entities.append(ExtractedEntity(f"amount:{name}", "Amount", name))
        return entities


def _coerce_relations(items: Iterable[Any]) -> list[ExtractedRelation]:
    result: list[ExtractedRelation] = []
    for item in items:
        if isinstance(item, ExtractedRelation):
            result.append(item)
            continue
        data = dict(item)
        result.append(ExtractedRelation(
            str(data.get("source", "")), str(data.get("predicate", "")),
            str(data.get("target", "")), dict(data.get("attributes") or {}),
        ))
    return [r for r in result if r.source and r.predicate and r.target]


class RelationExtractor:
    """规则抽取三元关系；``llm`` 注入后优先使用模型输出。"""

    def __init__(self, llm: LLMExtract | None = None) -> None:
        self.llm = llm

    def extract(self, text: str, entities: list[ExtractedEntity] | None = None
                ) -> list[ExtractedRelation]:
        if self.llm is not None:
            return _coerce_relations(self.llm(text))
        return _dedupe_relations(self._rule_extract(text))

    def _rule_extract(self, text: str) -> list[ExtractedRelation]:
        relations: list[ExtractedRelation] = []
        for source, target in _BELONGS_RE.findall(text):
            relations.append(ExtractedRelation(
                source.strip(), "BELONGS_TO", target.strip("类目类是 ")))
        for source, target in _SUPPORTS_RE.findall(text):
            relations.append(ExtractedRelation(source.strip(), "SUPPORTS", target.strip()))
        orders = _ORDER_CODE_RE.findall(text.upper())
        products = [p.upper() for p in _PRODUCT_CODE_RE.findall(text.upper())]
        products += _PRODUCT_RE.findall(text)
        for order in orders:
            for product in dict.fromkeys(products):
                relations.append(ExtractedRelation(order, "CONTAINS", product))
        return relations


def _dedupe_relations(relations: list[ExtractedRelation]) -> list[ExtractedRelation]:
    seen: set[tuple[str, str, str]] = set()
    result: list[ExtractedRelation] = []
    for relation in relations:
        key = (relation.source, relation.predicate, relation.target)
        if key not in seen:
            seen.add(key)
            result.append(relation)
    return result


class EventExtractor:
    """规则抽取事件及参数；``llm`` 注入后优先使用模型输出。"""

    def __init__(self, llm: LLMExtract | None = None) -> None:
        self.llm = llm

    def extract(self, text: str) -> list[ExtractedEvent]:
        if self.llm is not None:
            return _coerce_events(self.llm(text))
        return self._rule_extract(text)

    def _rule_extract(self, text: str) -> list[ExtractedEvent]:
        events: list[ExtractedEvent] = []
        clauses = [c.strip() for c in _CLAUSE_RE.split(text) if c.strip()]
        participants = _ORDER_CODE_RE.findall(text.upper()) + _PRODUCT_CODE_RE.findall(text.upper())
        for clause in clauses:
            for trigger, event_type in _EVENT_TYPES.items():
                if trigger not in clause:
                    continue
                arguments: dict[str, str] = {}
                duration = _DURATION_RE.search(clause)
                if duration:
                    arguments["时限"] = duration.group(0)
                amount = _AMOUNT_RE.search(clause)
                if amount:
                    arguments["金额"] = f"{amount.group(1)}元"
                condition = _CONDITION_RE.search(clause)
                if condition:
                    arguments["条件"] = condition.group(0).strip()
                for method in _METHODS:
                    if method in clause:
                        arguments["方式"] = method
                        break
                event_id = f"event:{event_type}:{len(events) + 1}"
                events.append(ExtractedEvent(
                    event_id, trigger, event_type, arguments, list(dict.fromkeys(participants)),
                ))
        return events


def _coerce_events(items: Iterable[Any]) -> list[ExtractedEvent]:
    result: list[ExtractedEvent] = []
    for item in items:
        if isinstance(item, ExtractedEvent):
            result.append(item)
            continue
        data = dict(item)
        result.append(ExtractedEvent(
            str(data.get("id", "")), str(data.get("trigger", "")),
            str(data.get("type", "Event")), dict(data.get("arguments") or {}),
            list(data.get("participants") or []),
        ))
    return [e for e in result if e.id and e.trigger]


def extract_knowledge(
    text: str,
    entity_extractor: EntityExtractor | None = None,
    relation_extractor: RelationExtractor | None = None,
    event_extractor: EventExtractor | None = None,
) -> KnowledgeGraphDraft:
    """编排实体 -> 关系 -> 事件三阶段抽取，返回知识图谱草稿。"""
    entity_extractor = entity_extractor or EntityExtractor()
    relation_extractor = relation_extractor or RelationExtractor()
    event_extractor = event_extractor or EventExtractor()
    entities = entity_extractor.extract(text)
    relations = relation_extractor.extract(text, entities)
    events = event_extractor.extract(text)
    return KnowledgeGraphDraft(entities, relations, events)


__all__ = [
    "ExtractedEntity", "ExtractedRelation", "ExtractedEvent", "KnowledgeGraphDraft",
    "EntityExtractor", "RelationExtractor", "EventExtractor", "extract_knowledge",
]
