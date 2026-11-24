"""Memory：会话记忆 / 长期记忆 / 用户记忆 三层分离。

  ConversationMemory  已由 LangGraph checkpointer + thread_id 承担（原有能力）
  LongTermStore       本模块：跨 thread 的 namespace/key 长期记忆，语义对齐 LangGraph BaseStore
  UserProfile         本模块：从对话抽取偏好，生成可注入 system prompt 的画像片段

关键区分：checkpointer 存「一次图运行的 messages 快照」；store 存「跨会话、按用户/租户
维度的事实」。把用户偏好塞进 messages 会随换 thread 丢失，也不利于按用户更新。
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryItem:
    namespace: tuple[str, ...]
    key: str
    value: Any
    version: int = 1
    updated_at: float = field(default_factory=time.time)
    ttl_seconds: float | None = None

    def expired(self) -> bool:
        return self.ttl_seconds is not None and time.time() - self.updated_at > self.ttl_seconds


class LongTermStore:
    """线程安全的内存 store。生产替换为 Postgres / Redis / LangGraph BaseStore 即可。

    接口与 LangGraph Store 对齐：put(namespace, key, value) / get / search / delete。
    """

    def __init__(self) -> None:
        self._data: dict[tuple[tuple[str, ...], str], MemoryItem] = {}
        self._lock = threading.RLock()

    def put(self, namespace: tuple[str, ...] | list[str], key: str,
            value: Any, ttl_seconds: float | None = None) -> MemoryItem:
        ns = tuple(namespace)
        with self._lock:
            old = self._data.get((ns, key))
            item = MemoryItem(
                namespace=ns, key=key, value=value,
                version=(old.version + 1) if old else 1,
                ttl_seconds=ttl_seconds,
            )
            self._data[(ns, key)] = item
            return item

    def get(self, namespace: tuple[str, ...] | list[str], key: str) -> MemoryItem | None:
        with self._lock:
            item = self._data.get((tuple(namespace), key))
            if item and item.expired():
                del self._data[(tuple(namespace), key)]
                return None
            return item

    def search(self, namespace_prefix: tuple[str, ...] | list[str],
               query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        prefix = tuple(namespace_prefix)
        with self._lock:
            items = [i for (ns, _), i in self._data.items()
                     if ns[: len(prefix)] == prefix and not i.expired()]
        if query:
            q = query.lower()
            items = [i for i in items if q in i.key.lower() or q in str(i.value).lower()]
        items.sort(key=lambda i: i.updated_at, reverse=True)
        return [{"namespace": list(i.namespace), "key": i.key, "value": i.value,
                 "version": i.version, "updated_at": i.updated_at} for i in items[:limit]]

    def delete(self, namespace: tuple[str, ...] | list[str], key: str) -> bool:
        with self._lock:
            return self._data.pop((tuple(namespace), key), None) is not None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"total_items": len(self._data),
                    "namespaces": sorted({"/".join(ns) for ns, _ in self._data})}


STORE = LongTermStore()


_BUDGET_RE = re.compile(r"预算\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*元(?:以内|以下)?")
_CATEGORY_WORDS = {"数码": ("耳机", "键盘", "风扇", "数码"),
                   "家居": ("枕头", "乳胶", "家居")}
_BRAND_RE = re.compile(r"(星野|云眠|清风|北岸)")


def extract_facts(message: str) -> dict[str, Any]:
    """从一句话里抽取可长期保留的结构化事实（规则实现，可替换为 LLM 抽取器）。"""
    facts: dict[str, Any] = {}
    m = _BUDGET_RE.search(message)
    if m:
        facts["budget_max"] = float(m.group(1) or m.group(2))
    for cat, words in _CATEGORY_WORDS.items():
        if any(w in message for w in words):
            facts["preferred_category"] = cat
            break
    b = _BRAND_RE.search(message)
    if b:
        facts["preferred_brand"] = b.group(1)
    if any(k in message for k in ("降噪", "静音")):
        facts["preference"] = "降噪"
    return facts


def update_user_profile(user_id: str, message: str, store: LongTermStore | None = None) -> dict[str, Any]:
    """合并事实到用户画像：同一 key 覆盖并递增版本，返回本次写入画像。"""
    s = store or STORE
    ns = ("users", user_id, "profile")
    profile = {}
    existing = s.get(ns, "preferences")
    if existing and isinstance(existing.value, dict):
        profile.update(existing.value)
    new_facts = extract_facts(message)
    profile.update(new_facts)
    profile["updated_turns"] = profile.get("updated_turns", 0) + 1
    item = s.put(ns, "preferences", profile)
    return {"namespace": list(ns), "key": "preferences", "value": profile,
            "version": item.version, "extracted": new_facts}


def remember_fact(user_id: str, key: str, value: Any,
                  ttl_seconds: float | None = None,
                  store: LongTermStore | None = None) -> dict[str, Any]:
    s = store or STORE
    item = s.put(("users", user_id, "facts"), key, value, ttl_seconds=ttl_seconds)
    return {"namespace": list(item.namespace), "key": key, "value": value,
            "version": item.version, "ttl_seconds": ttl_seconds}


def build_memory_context(user_id: str, store: LongTermStore | None = None,
                         max_chars: int = 400) -> str:
    """把长期记忆压成可注入 system prompt 的短片段，受 Token 预算约束。"""
    s = store or STORE
    item = s.get(("users", user_id, "profile"), "preferences")
    if not item or not isinstance(item.value, dict):
        return ""
    parts = []
    for k, v in item.value.items():
        if k == "updated_turns":
            continue
        parts.append(f"{k}={v}")
    facts = s.search(("users", user_id, "facts"), limit=5)
    parts.extend(f"{f['key']}={f['value']}" for f in facts)
    return ("用户长期记忆：" + "；".join(parts))[:max_chars]


def memory_layers(user_id: str, thread_id: str) -> dict[str, Any]:
    """三层记忆的可解释视图，供 /v2/capabilities 与面试讲解使用。"""
    return {
        "conversation": {"mechanism": "LangGraph checkpointer (InMemorySaver)",
                         "scope": f"thread:{thread_id}", "survives_new_thread": False},
        "long_term": {"mechanism": "LongTermStore namespace/key",
                      "scope": ("users", user_id, "profile"), "survives_new_thread": True},
        "user": {"mechanism": "extract_facts + merge",
                 "scope": "preferences / facts", "survives_new_thread": True},
    }
