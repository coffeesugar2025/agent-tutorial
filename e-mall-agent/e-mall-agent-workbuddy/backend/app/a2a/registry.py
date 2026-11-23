"""协议无关的 Agent Card 注册中心。

只负责「按名字/技能发现 Agent」的内存索引，不含 HTTP/gRPC/RPC 细节；
把 endpoint 换成任意传输适配器即可用于真实 A2A 网络。
"""
from __future__ import annotations

import threading

from .models import AgentCard


class AgentCardRegistry:
    """线程安全的 AgentCard 注册表。"""

    def __init__(self, cards: list[AgentCard] | None = None) -> None:
        self._lock = threading.RLock()
        self._cards: dict[str, AgentCard] = {}
        for card in cards or []:
            self.register(card)

    def register(self, card: AgentCard) -> AgentCard:
        """注册名片；同名重复注册会抛 ValueError。"""
        with self._lock:
            if card.name in self._cards:
                raise ValueError(f"AgentCard 已存在: {card.name}")
            self._cards[card.name] = card
            return card

    def unregister(self, name: str) -> bool:
        """取消注册，返回是否确实删除了名片。"""
        with self._lock:
            return self._cards.pop(name, None) is not None

    def get(self, name: str) -> AgentCard | None:
        """按名称查找，不存在返回 None。"""
        with self._lock:
            return self._cards.get(name)

    def require(self, name: str) -> AgentCard:
        """按名称查找，不存在抛 KeyError。"""
        card = self.get(name)
        if card is None:
            raise KeyError(f"未注册的 Agent: {name}")
        return card

    def list(self) -> list[AgentCard]:
        """按名称排序列出全部名片，便于确定性断言。"""
        with self._lock:
            return [self._cards[name] for name in sorted(self._cards)]

    def find_by_skill(self, skill_id: str) -> list[AgentCard]:
        """按技能 id 查找具备该能力的 Agent。"""
        with self._lock:
            return [card for card in self.list() if skill_id in card.skill_ids()]

    def search(self, query: str) -> list[AgentCard]:
        """按关键词在名称、描述、技能名与标签中做轻量匹配。"""
        keyword = (query or "").strip().lower()
        if not keyword:
            return self.list()
        hits = []
        for card in self.list():
            haystack = [card.name, card.description]
            for skill in card.skills:
                haystack.extend([skill.name, skill.description, *skill.tags])
            if any(keyword in text.lower() for text in haystack if text):
                hits.append(card)
        return hits
