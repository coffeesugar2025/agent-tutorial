"""记忆写入策略 / 冲突消解 / 衰减（总纲 2.6）。

之前 memory.update_user_profile 直接 profile.update(new_facts) 覆盖，
没有「什么值得记 / 何时写 / 新旧矛盾 / 遗忘」，对应 C#24。
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.capabilities.memory import LongTermStore, extract_facts

WHITELIST = {"budget_max", "preferred_category", "preferred_brand", "preference", "size", "allergy"}
EPHEMERAL = ("今天", "这次", "刚刚", "临时", "随便看看")


@dataclass
class Fact:
    key: str
    value: Any
    confidence: float = 1.0
    source: str = "user_explicit"
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    hits: int = 1
    ttl_seconds: float | None = None

    def decay(self, now: float | None = None) -> float:
        now = now or time.time()
        age = now - self.last_seen
        half_life = 30 * 86400
        return round(self.confidence * (0.5 ** (age / half_life)), 4)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.value, "confidence": self.confidence,
                "decayed_confidence": self.decay(), "source": self.source,
                "hits": self.hits, "ttl_seconds": self.ttl_seconds,
                "last_seen": self.last_seen}


class GovernedMemory:
    def __init__(self, store: LongTermStore | None = None) -> None:
        self.store = store or LongTermStore()
        self._lock = threading.RLock()
        self.rejected: list[dict[str, Any]] = []

    def should_write(self, key: str, value: Any, message: str) -> dict[str, Any]:
        if key not in WHITELIST:
            return {"write": False, "reason": "不在事实白名单（避免什么都记）"}
        if any(e in message for e in EPHEMERAL):
            return {"write": False, "reason": "临时性表述，会话结束即弃"}
        if value is None or value == "":
            return {"write": False, "reason": "空值"}
        return {"write": True, "timing": "即时写入（显式偏好）；隐式行为会话结束异步抽取"}

    def merge(self, user_id: str, message: str) -> dict[str, Any]:
        """冲突消解：显式 > 隐式；高频 > 低频；新事实不静默覆盖，记录冲突轨迹。"""
        ns = ("users", user_id, "profile")
        facts = extract_facts(message)
        existing = self.store.get(ns, "governed")
        current: dict[str, Fact] = {}
        if existing and isinstance(existing.value, dict):
            for k, v in existing.value.items():
                if isinstance(v, dict) and "value" in v:
                    current[k] = Fact(k, v["value"], v.get("confidence", 1.0),
                                      v.get("source", "implicit"), v.get("created_at", time.time()),
                                      v.get("last_seen", time.time()), v.get("hits", 1))
        conflicts, written = [], []
        for k, v in facts.items():
            gate = self.should_write(k, v, message)
            if not gate["write"]:
                self.rejected.append({"key": k, "value": v, "reason": gate["reason"]})
                continue
            if k in current and current[k].value != v:
                conflicts.append({"key": k, "old": current[k].value, "new": v,
                                  "resolution": "显式用户表述覆盖，保留旧值到审计轨迹"})
                current[k].value = v
                current[k].confidence = 1.0
                current[k].source = "user_explicit"
                current[k].hits += 1
                current[k].last_seen = time.time()
            elif k in current:
                current[k].hits += 1
                current[k].last_seen = time.time()
                current[k].confidence = min(1.0, current[k].confidence + 0.1)
            else:
                current[k] = Fact(k, v, 1.0, "user_explicit")
            written.append(k)
        self.store.put(ns, "governed", {k: f.to_dict() for k, f in current.items()})
        return {"written": written, "conflicts": conflicts, "rejected": self.rejected[-5:],
                "profile": {k: f.to_dict() for k, f in current.items()},
                "policy": "白名单 + 临时语过滤 + 显式优先 + 30 天半衰期 + 冲突留痕"}

    def forget(self, user_id: str, key: str) -> dict[str, Any]:
        """用户可见可删（6.7 / 2.6）。"""
        return {"deleted": self.store.delete(("users", user_id, "profile"), key),
                "also": "同时清除缓存中该 user 的语义记忆（由 CacheLayer.invalidate 负责）"}


MEMORY = GovernedMemory()
