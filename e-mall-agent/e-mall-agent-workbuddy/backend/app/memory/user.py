"""用户长期记忆：画像、带置信度的偏好、带来源与过期时间的事实。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from ..domain.models import utcnow
from .episodic import _expiry_from_ttl, _is_expired
from .store import user_namespace, MemoryStore


@dataclass
class Preference:
    """一条用户偏好。"""

    name: str
    value: str
    confidence: float
    updated_at: str = field(default_factory=utcnow)

    def as_dict(self) -> dict[str, Any]:
        """转为可序列化字典。"""
        return {
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "updated_at": self.updated_at,
        }


@dataclass
class Fact:
    """一条带来源与过期时间的事实。"""

    id: str
    content: str
    source: str
    created_at: str = field(default_factory=utcnow)
    expires_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """转为可序列化字典。"""
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


class UserMemory:
    """按 ``user_id`` 严格隔离的用户长期记忆。

    同一用户的所有数据存放在独立命名空间中；不存在跨用户读取路径。
    偏好在重复确认同一取值时置信度递增，取值变化时以新证据置信度覆盖。
    事实在读取时按 ``expires_at`` 过滤，永不过期的事实 ``expires_at`` 为 ``None``。
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def _empty(self) -> dict[str, Any]:
        return {"profile": {}, "preferences": {}, "facts": {}}

    def _load(self, user_id: str) -> dict[str, Any]:
        raw = self.store.get(user_namespace(user_id), "record")
        if raw is None:
            return self._empty()
        return {
            "profile": dict(raw.get("profile", {})),
            "preferences": {k: Preference(**v)
                            for k, v in raw.get("preferences", {}).items()},
            "facts": {k: Fact(**v) for k, v in raw.get("facts", {}).items()},
        }

    def _save(self, user_id: str, record: dict[str, Any]) -> None:
        self.store.set(user_namespace(user_id), "record", {
            "profile": dict(record["profile"]),
            "preferences": {k: v.as_dict() for k, v in record["preferences"].items()},
            "facts": {k: v.as_dict() for k, v in record["facts"].items()},
        })

    # ---------- profile ----------
    def set_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        """整体设置用户画像（静态属性），如姓名、角色、会员等级。"""
        with self.store.lock():
            record = self._load(user_id)
            record["profile"] = dict(profile)
            self._save(user_id, record)

    def get_profile(self, user_id: str) -> dict[str, Any]:
        """返回用户画像副本。"""
        return self._load(user_id)["profile"]

    # ---------- preferences ----------
    def upsert_preference(
        self, user_id: str, name: str, value: str, confidence: float = 0.6
    ) -> Preference:
        """新增或更新一条偏好。

        同名同值时视为再次确认，置信度增加 ``0.1``（上限 1.0）；
        同名不同值时以本次证据为准，取 ``confidence``（截断到 0..1）。
        """
        confidence = max(0.0, min(1.0, confidence))
        with self.store.lock():
            record = self._load(user_id)
            existing = record["preferences"].get(name)
            if existing is not None and existing.value == value:
                new_confidence = min(1.0, round(existing.confidence + 0.1, 4))
            else:
                new_confidence = confidence
            pref = Preference(name=name, value=value,
                              confidence=new_confidence, updated_at=utcnow())
            record["preferences"][name] = pref
            self._save(user_id, record)
            return pref

    def get_preference(self, user_id: str, name: str) -> Preference | None:
        """读取单条偏好；不存在返回 ``None``。"""
        return self._load(user_id)["preferences"].get(name)

    # ---------- facts ----------
    def add_fact(
        self, user_id: str, content: str, source: str,
        ttl_seconds: int | None = None,
    ) -> Fact:
        """新增一条事实，记录来源与可选的过期时间。"""
        fact = Fact(
            id=f"fact_{uuid.uuid4().hex[:12]}",
            content=content,
            source=source,
            expires_at=_expiry_from_ttl(ttl_seconds),
        )
        with self.store.lock():
            record = self._load(user_id)
            record["facts"][fact.id] = fact
            self._save(user_id, record)
        return fact

    def list_facts(self, user_id: str) -> list[Fact]:
        """列出未过期事实（最新优先）。"""
        facts = [f for f in self._load(user_id)["facts"].values()
                 if not _is_expired(f.expires_at)]
        return sorted(facts, key=lambda f: f.created_at, reverse=True)

    # ---------- forget ----------
    def forget(
        self,
        user_id: str,
        target: Literal["profile", "preference", "fact", "all"],
        *,
        key: str | None = None,
    ) -> int:
        """按目标遗忘数据，返回实际删除的条目数。

        :param target: ``profile`` / ``preference`` / ``fact`` / ``all``。
        :param key: ``preference`` 时为偏好名，``fact`` 时为事实 id。
        """
        with self.store.lock():
            if target == "all":
                existed = self.store.delete_namespace(user_namespace(user_id))
                return 1 if existed else 0
            record = self._load(user_id)
            if target == "profile":
                count = 1 if record["profile"] else 0
                record["profile"] = {}
            elif target == "preference":
                if not key:
                    raise ValueError("删除偏好需要指定 key（偏好名）")
                count = 1 if record["preferences"].pop(key, None) else 0
            elif target == "fact":
                if not key:
                    raise ValueError("删除事实需要指定 key（事实 id）")
                count = 1 if record["facts"].pop(key, None) else 0
            else:
                raise ValueError(f"不支持的遗忘目标: {target}")
            self._save(user_id, record)
            return count

    # ---------- summary ----------
    def get_profile_summary(self, user_id: str) -> str:
        """生成可直接拼入 system prompt 的中文自然语言摘要。

        仅包含该用户自己的画像、偏好与未过期事实；无数据时返回空串。
        """
        record = self._load(user_id)
        lines: list[str] = []
        if record["profile"]:
            parts = [f"{k}={v}" for k, v in record["profile"].items()]
            lines.append("用户画像：" + "，".join(parts) + "。")
        if record["preferences"]:
            parts = [f"{p.name}={p.value}（置信度 {p.confidence:.2f}）"
                     for p in record["preferences"].values()]
            lines.append("用户偏好：" + "；".join(parts) + "。")
        facts = [f for f in record["facts"].values() if not _is_expired(f.expires_at)]
        if facts:
            parts = [f"{f.content}（来源: {f.source}）" for f in facts]
            lines.append("已知事实：" + "；".join(parts) + "。")
        return "\n".join(lines)

    def stats(self, user_id: str) -> dict[str, int]:
        """返回该用户画像字段数、偏好数、有效事实数。"""
        record = self._load(user_id)
        return {
            "profile_fields": len(record["profile"]),
            "preferences": len(record["preferences"]),
            "facts": sum(1 for f in record["facts"].values()
                         if not _is_expired(f.expires_at)),
        }
