"""情景记忆：一次完整任务/对话的记录，支持检索、TTL 过期与滚动淘汰。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..domain.models import utcnow
from .store import episodic_namespace, MemoryStore


@dataclass
class Episode:
    """一条情景记忆记录。"""

    id: str
    user_id: str
    thread_id: str
    goal: str
    steps: list[str] = field(default_factory=list)
    outcome: str = ""
    ts: str = field(default_factory=utcnow)
    tags: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """拼接可检索文本（目标、步骤、结果、标签）。"""
        return " ".join([self.goal, *self.steps, self.outcome, *self.tags])

    def as_dict(self) -> dict[str, Any]:
        """转为可序列化字典。"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "goal": self.goal,
            "steps": list(self.steps),
            "outcome": self.outcome,
            "ts": self.ts,
            "tags": list(self.tags),
        }


def _expiry_from_ttl(ttl_seconds: int | None) -> str | None:
    """把 TTL 秒数换算为 UTC ISO 过期时间；``None`` 表示永不过期。"""
    if ttl_seconds is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")


def _is_expired(expires_at: str | None) -> bool:
    """判断是否已过期。"""
    if not expires_at:
        return False
    return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)


class EpisodicMemory:
    """按 ``user_id`` 分命名空间的情景记忆。

    每条记录可设置 TTL；读取时惰性清理过期记录。超过 ``max_episodes`` 时
    按写入顺序淘汰最老的记录（滚动窗口）。所有查询都限定在目标用户的
    命名空间内，A 用户永远无法检索到 B 用户的记录。
    """

    def __init__(self, store: MemoryStore, max_episodes: int = 50,
                 default_ttl_seconds: int | None = None) -> None:
        if max_episodes < 1:
            raise ValueError("max_episodes 必须 >= 1")
        self.store = store
        self.max_episodes = max_episodes
        self.default_ttl_seconds = default_ttl_seconds
        self._seq = 0

    def _load_raw(self, user_id: str, episode_id: str) -> dict[str, Any] | None:
        return self.store.get(episodic_namespace(user_id), episode_id)

    def _save_raw(self, user_id: str, episode_id: str, raw: dict[str, Any]) -> None:
        self.store.set(episodic_namespace(user_id), episode_id, raw)

    def _purge_expired(self, user_id: str) -> None:
        """清理该用户所有已过期的记录。"""
        ns = episodic_namespace(user_id)
        for key in self.store.keys(ns):
            raw = self.store.get(ns, key)
            if raw and _is_expired(raw.get("expires_at")):
                self.store.delete(ns, key)

    def record(
        self,
        user_id: str,
        thread_id: str,
        goal: str,
        steps: list[str] | None = None,
        outcome: str = "",
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
    ) -> Episode:
        """写入一条情景记忆并执行滚动淘汰；返回写入的记录。

        :param ttl_seconds: 覆盖默认 TTL；``None`` 表示使用默认值。
        """
        episode = Episode(
            id=f"ep_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            thread_id=thread_id,
            goal=goal,
            steps=list(steps or []),
            outcome=outcome,
            tags=list(tags or []),
        )
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        with self.store.lock():
            ns = episodic_namespace(user_id)
            self._purge_expired(user_id)
            self._seq += 1
            self._save_raw(user_id, episode.id, {
                "episode": episode.as_dict(),
                "expires_at": _expiry_from_ttl(ttl),
                "seq": self._seq,
            })
            keys = self.store.keys(ns)
            if len(keys) > self.max_episodes:
                # 按 seq 升序淘汰最老的记录
                ordered = sorted(
                    keys,
                    key=lambda k: (self.store.get(ns, k) or {}).get("seq", 0),
                )
                for stale in ordered[: len(keys) - self.max_episodes]:
                    self.store.delete(ns, stale)
        return episode

    def get(self, user_id: str, episode_id: str) -> Episode | None:
        """按 id 读取记录；不存在或已过期返回 ``None``。"""
        with self.store.lock():
            raw = self._load_raw(user_id, episode_id)
            if raw is None:
                return None
            if _is_expired(raw.get("expires_at")):
                self.store.delete(episodic_namespace(user_id), episode_id)
                return None
            return Episode(**raw["episode"])

    def list(self, user_id: str, thread_id: str | None = None) -> list[Episode]:
        """列出用户记录（最新优先），可按 ``thread_id`` 过滤；自动清理过期项。"""
        with self.store.lock():
            self._purge_expired(user_id)
            ns = episodic_namespace(user_id)
            items = []
            for key in self.store.keys(ns):
                raw = self.store.get(ns, key)
                if raw is None:
                    continue
                episode = Episode(**raw["episode"])
                if thread_id is not None and episode.thread_id != thread_id:
                    continue
                items.append((raw.get("seq", 0), episode))
            items.sort(key=lambda pair: (pair[1].ts, pair[0]), reverse=True)
            return [episode for _, episode in items]

    def search(
        self,
        user_id: str,
        query: str,
        *,
        thread_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 3,
    ) -> list[Episode]:
        """按关键词相关性检索（再按时间倒序打破平局），自动过滤过期项。

        相关性得分 = 查询词在目标/步骤/结果/标签中出现的次数，
        命中 ``goal`` 与 ``tags`` 额外加权。
        """
        keywords = [k for k in (query or "").split() if k]
        if not tags and not keywords:
            return []
        scored: list[tuple[float, str, int, Episode]] = []
        with self.store.lock():
            for episode in self.list(user_id, thread_id=thread_id):
                text = episode.text
                score = float(sum(text.count(k) for k in keywords))
                score += sum(2.0 for k in keywords if k in episode.goal)
                score += sum(1.5 for t in (tags or []) if t in episode.tags)
                if tags and not any(t in episode.tags for t in tags):
                    continue
                if score <= 0:
                    continue
                raw = self._load_raw(user_id, episode.id) or {}
                scored.append((score, episode.ts, raw.get("seq", 0), episode))
        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in scored[:limit]]

    def delete(self, user_id: str, episode_id: str) -> bool:
        """删除指定记录；返回是否实际删除。"""
        with self.store.lock():
            return self.store.delete(episodic_namespace(user_id), episode_id)

    def clear(self, user_id: str) -> None:
        """清空指定用户的全部情景记忆。"""
        with self.store.lock():
            self.store.delete_namespace(episodic_namespace(user_id))

    def stats(self, user_id: str) -> dict[str, int]:
        """返回该用户有效记录数统计。"""
        with self.store.lock():
            self._purge_expired(user_id)
            return {"episodes": len(self.store.keys(episodic_namespace(user_id)))}
