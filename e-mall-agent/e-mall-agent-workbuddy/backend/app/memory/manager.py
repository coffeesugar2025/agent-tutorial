"""统一记忆门面：按相关性与截止时间融合三层记忆，提供合规删除能力。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context.engine import estimate_tokens
from .episodic import Episode, EpisodicMemory
from .store import (
    WORKING_NAMESPACE,
    episodic_namespace,
    user_namespace,
    InMemoryMemoryStore,
    MemoryStore,
)
from .user import UserMemory
from .working import Turn, WorkingMemory


@dataclass
class RecallResult:
    """一次召回的结果。

    ``injected_context`` 的章节顺序固定为：用户长期记忆 -> 相关经历 -> 近期会话，
    便于上层稳定地拼入 system prompt 并进行可解释性展示。
    """

    working: list[Turn]
    episodes: list[Episode]
    user_summary: str
    injected_context: str
    token_estimate: int

    def as_dict(self) -> dict[str, Any]:
        """转为可序列化字典（不含完整对象，仅含要点）。"""
        return {
            "working": [t.as_dict() for t in self.working],
            "episodes": [e.as_dict() for e in self.episodes],
            "user_summary": self.user_summary,
            "injected_context": self.injected_context,
            "token_estimate": self.token_estimate,
        }


class MemoryManager:
    """记忆系统统一入口：写入走 :meth:`remember`，读取走 :meth:`recall`。

    工作记忆的键由 ``user_id`` 与 ``thread_id`` 组合而成，确保即使用户之间
    恰好使用相同的 thread_id，也不会互相看到对方的会话内容。
    """

    def __init__(
        self,
        store: MemoryStore | None = None,
        *,
        working: WorkingMemory | None = None,
        episodic: EpisodicMemory | None = None,
        user: UserMemory | None = None,
        max_inject_chars: int = 1600,
        episode_limit: int = 3,
    ) -> None:
        self.store = store or InMemoryMemoryStore()
        self.working = working or WorkingMemory(self.store)
        self.episodic = episodic or EpisodicMemory(self.store)
        self.user = user or UserMemory(self.store)
        self.max_inject_chars = max_inject_chars
        self.episode_limit = episode_limit

    @staticmethod
    def _thread_key(user_id: str, thread_id: str) -> str:
        """组合用户与会话标识，作为工作记忆的内部键。"""
        return f"{user_id}::{thread_id}"

    def recall(
        self, user_id: str, thread_id: str, query: str,
        *, episode_limit: int | None = None,
    ) -> RecallResult:
        """融合三层记忆并返回可注入上下文的召回结果。

        融合规则：情景记忆先按关键词相关性打分、再按时间倒序，并剔除过期项；
        用户记忆只注入未过期事实；工作记忆附带被淘汰轮次的压缩摘要。
        """
        working = self.working.get(self._thread_key(user_id, thread_id))
        summary = self.working.get_summary(self._thread_key(user_id, thread_id))
        episodes = self.episodic.search(
            user_id, query, limit=episode_limit or self.episode_limit
        )
        user_summary = self.user.get_profile_summary(user_id)

        sections: list[str] = []
        if user_summary:
            sections.append(f"[用户长期记忆]\n{user_summary}")
        if episodes:
            lines = [
                f"- 目标: {e.goal}；结果: {e.outcome}"
                + (f"；标签: {', '.join(e.tags)}" if e.tags else "")
                for e in episodes
            ]
            sections.append("[相关经历]\n" + "\n".join(lines))
        session_lines: list[str] = []
        if summary:
            session_lines.append(summary)
        session_lines.extend(f"用户: {t.user} / 助手: {t.assistant}" for t in working)
        if session_lines:
            sections.append("[近期会话]\n" + "\n".join(session_lines))

        injected = "\n\n".join(sections)
        if len(injected) > self.max_inject_chars:
            injected = injected[: max(0, self.max_inject_chars - 1)] + "…"
        return RecallResult(
            working=working,
            episodes=episodes,
            user_summary=user_summary,
            injected_context=injected,
            token_estimate=estimate_tokens(injected),
        )

    def remember(
        self,
        user_id: str,
        thread_id: str,
        user: str,
        assistant: str,
        *,
        metadata: dict[str, Any] | None = None,
        importance: float = 1.0,
        goal: str | None = None,
        steps: list[str] | None = None,
        outcome: str | None = None,
        tags: list[str] | None = None,
        ttl_seconds: int | None = None,
    ) -> Episode | None:
        """统一写入：必写工作记忆，提供 ``goal`` 时另写一条情景记忆。

        :return: 写入的情景记忆；未写入时返回 ``None``。
        """
        self.working.add(
            self._thread_key(user_id, thread_id), user, assistant,
            metadata=metadata, importance=importance,
        )
        if goal is None:
            return None
        return self.episodic.record(
            user_id, thread_id, goal,
            steps=steps, outcome=outcome or assistant,
            tags=tags, ttl_seconds=ttl_seconds,
        )

    def forget_user(self, user_id: str) -> dict[str, int]:
        """彻底删除某用户的全部记忆（工作、情景、用户长期记忆）。

        返回各层实际删除的条目数，便于合规审计。
        """
        with self.store.lock():
            ep_ns = episodic_namespace(user_id)
            episodes = len(self.store.keys(ep_ns))
            self.store.delete_namespace(ep_ns)

            u_ns = user_namespace(user_id)
            user_records = 1 if self.store.delete_namespace(u_ns) else 0

            prefix = f"{user_id}::"
            working = 0
            for key in self.store.keys(WORKING_NAMESPACE):
                if key.startswith(prefix):
                    if self.store.delete(WORKING_NAMESPACE, key):
                        working += 1
        return {"working": working, "episodes": episodes, "user": user_records}
