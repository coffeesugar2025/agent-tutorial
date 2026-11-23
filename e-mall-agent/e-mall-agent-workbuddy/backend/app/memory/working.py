"""工作记忆（会话级短期记忆）：线程隔离、按重要度淘汰并生成压缩摘要。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.models import utcnow
from .store import WORKING_NAMESPACE, MemoryStore


@dataclass
class Turn:
    """一轮对话记录。"""

    user: str
    assistant: str
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=utcnow)
    importance: float = 1.0

    @property
    def chars(self) -> int:
        """该轮对话占用的字符数。"""
        return len(self.user) + len(self.assistant)

    def as_dict(self) -> dict[str, Any]:
        """转为可序列化字典。"""
        return {
            "user": self.user,
            "assistant": self.assistant,
            "metadata": dict(self.metadata),
            "ts": self.ts,
            "importance": self.importance,
        }


@dataclass
class _ThreadState:
    """线程内部状态：保留轮次、被淘汰轮次与压缩摘要。"""

    turns: list[Turn] = field(default_factory=list)
    evicted: list[Turn] = field(default_factory=list)
    summary: str = ""


class WorkingMemory:
    """会话级短期记忆，按 ``thread_id`` 完全隔离。

    超过 ``max_turns`` 轮或 ``max_chars`` 字符时，按重要度从低到高淘汰
    （同重要度淘汰最早的一轮），并用被淘汰的轮次生成一段压缩摘要，
    以便上层在注入上下文时仍能保留被丢弃对话的要点。
    """

    def __init__(
        self,
        store: MemoryStore,
        max_turns: int = 8,
        max_chars: int | None = None,
        summary_max_chars: int = 240,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns 必须 >= 1")
        self.store = store
        self.max_turns = max_turns
        self.max_chars = max_chars
        self.summary_max_chars = summary_max_chars

    def _load(self, thread_id: str) -> _ThreadState:
        raw = self.store.get(WORKING_NAMESPACE, thread_id)
        if raw is None:
            return _ThreadState()
        return _ThreadState(
            turns=[Turn(**t) for t in raw.get("turns", [])],
            evicted=[Turn(**t) for t in raw.get("evicted", [])],
            summary=raw.get("summary", ""),
        )

    def _save(self, thread_id: str, state: _ThreadState) -> None:
        self.store.set(WORKING_NAMESPACE, thread_id, {
            "turns": [t.as_dict() for t in state.turns],
            "evicted": [t.as_dict() for t in state.evicted],
            "summary": state.summary,
        })

    def _compress(self, evicted: list[Turn]) -> str:
        """根据被淘汰的轮次生成有界的中文压缩摘要。"""
        if not evicted:
            return ""
        parts = [f"用户:{t.user}->助手:{t.assistant}" for t in evicted]
        text = "[历史摘要] " + "；".join(parts)
        if len(text) > self.summary_max_chars:
            text = text[: max(0, self.summary_max_chars - 1)] + "…"
        return text

    def _enforce_budget(self, state: _ThreadState) -> None:
        """循环淘汰直到轮数与字符预算均满足。"""
        while state.turns:
            total_chars = sum(t.chars for t in state.turns)
            over_turns = len(state.turns) > self.max_turns
            over_chars = self.max_chars is not None and total_chars > self.max_chars
            if not over_turns and not over_chars:
                break
            # 最低重要度优先；同分取最早（列表中小索引）
            victim = min(range(len(state.turns)),
                         key=lambda i: (state.turns[i].importance, i))
            state.evicted.append(state.turns.pop(victim))
        state.summary = self._compress(state.evicted)

    def add(
        self,
        thread_id: str,
        user: str,
        assistant: str,
        metadata: dict[str, Any] | None = None,
        *,
        importance: float = 1.0,
    ) -> Turn:
        """向指定会话追加一轮对话；返回实际写入的轮次。

        :param thread_id: 会话（线程）标识，线程间数据互不可见。
        :param user: 用户输入。
        :param assistant: 助手回答。
        :param metadata: 附加元数据（如 trace_id、来源）。
        :param importance: 重要度，越大越不易在超限时被淘汰。
        """
        turn = Turn(user=user, assistant=assistant,
                    metadata=dict(metadata or {}), importance=importance)
        with self.store.lock():
            state = self._load(thread_id)
            state.turns.append(turn)
            self._enforce_budget(state)
            self._save(thread_id, state)
        return turn

    def get(self, thread_id: str) -> list[Turn]:
        """返回该会话保留的轮次（深拷贝，修改不影响内部状态）。"""
        return self._load(thread_id).turns

    def get_summary(self, thread_id: str) -> str:
        """返回该会话被淘汰轮次生成的压缩摘要。"""
        return self._load(thread_id).summary

    def snapshot(self, thread_id: str) -> dict[str, Any]:
        """返回含摘要与轮次的完整快照，便于注入上下文。"""
        state = self._load(thread_id)
        return {
            "summary": state.summary,
            "turns": [t.as_dict() for t in state.turns],
            "evicted_count": len(state.evicted),
        }

    def clear(self, thread_id: str | None = None) -> None:
        """清空指定会话；``thread_id`` 为 ``None`` 时清空全部会话。"""
        with self.store.lock():
            if thread_id is None:
                for key in self.store.keys(WORKING_NAMESPACE):
                    self.store.delete(WORKING_NAMESPACE, key)
            else:
                self.store.delete(WORKING_NAMESPACE, thread_id)

    def stats(self) -> dict[str, int]:
        """返回线程数、总轮次、总淘汰数与摘要数等统计信息。"""
        threads = 0
        turns = 0
        evicted = 0
        summaries = 0
        with self.store.lock():
            for key in self.store.keys(WORKING_NAMESPACE):
                state = self._load(key)
                threads += 1
                turns += len(state.turns)
                evicted += len(state.evicted)
                if state.summary:
                    summaries += 1
        return {
            "threads": threads,
            "turns": turns,
            "evicted": evicted,
            "summaries": summaries,
        }
