"""Context engineering: priority-based packing, sliding window and summarisation marker.

The engine is intentionally framework-agnostic and unit-testable. It produces a
visualisable snapshot so the frontend can show exactly what entered the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ..config import get_settings


def estimate_tokens(text: str) -> int:
    """Cheap heuristic (no tokenizer dependency): ~1.5 Chinese chars / token."""
    return max(1, ceil(len(text or "") / 1.5))


@dataclass
class ContextSection:
    name: str
    content: str
    priority: int  # lower = more important
    chars: int = 0

    def __post_init__(self) -> None:
        self.chars = len(self.content)


@dataclass
class ContextSnapshot:
    sections: list[dict[str, Any]] = field(default_factory=list)
    max_chars: int = 0
    total_chars: int = 0
    kept_messages: int = 0
    dropped_messages: int = 0
    compressed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "sections": self.sections,
            "max_chars": self.max_chars,
            "total_chars": self.total_chars,
            "kept_messages": self.kept_messages,
            "dropped_messages": self.dropped_messages,
            "compressed": self.compressed,
        }


class ContextEngine:
    def __init__(self, max_chars: int | None = None, recent_messages: int | None = None) -> None:
        settings = get_settings()
        self.max_chars = max_chars or settings.context_max_chars
        self.recent_messages = recent_messages or settings.context_recent_messages

    @staticmethod
    def format_docs(docs: Iterable[dict[str, Any]]) -> str:
        lines = []
        for doc in docs:
            source = doc.get("source") or doc.get("metadata", {}).get("source", "知识库")
            lines.append(f"- [{source}] {doc.get('content', '')}")
        return "\n".join(lines)

    @staticmethod
    def format_tools(tools: Iterable[Any]) -> str:
        lines = []
        for tool in tools:
            name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
            description = (getattr(tool, "description", None)
                           or getattr(tool, "__doc__", "") or "").strip()
            first_line = description.splitlines()[0] if description else ""
            lines.append(f"- {name}: {first_line}")
        return "\n".join(lines)

    def compact(self, history: list[BaseMessage], budget_chars: int) -> tuple[list[BaseMessage], int, bool]:
        """Keep the most recent turns inside the char budget; truncate a long turn."""
        kept: list[BaseMessage] = []
        total = 0
        compressed = False
        eligible = [m for m in history if not isinstance(m, SystemMessage)]
        for message in reversed(eligible[-self.recent_messages:]):
            text = str(message.content or "")
            allowance = budget_chars - total
            if allowance <= 0:
                break
            if len(text) > allowance:
                head = allowance // 2
                tail = allowance - head - 12
                if tail > 0:
                    clipped = text[:head] + " …[上下文已压缩]… " + text[-tail:]
                else:
                    clipped = text[: max(0, allowance - 12)] + "…[已压缩]"
                message = type(message)(content=clipped)
                compressed = True
                total += len(clipped)
                kept.append(message)
                break
            total += len(text)
            kept.append(message)
        kept.reverse()
        return kept, len(eligible) - len(kept), compressed

    def build(
        self,
        *,
        persona: str,
        user: Any,
        retrieved_docs: list[dict[str, Any]] | None = None,
        tools: list[Any] | None = None,
        history: list[BaseMessage] | None = None,
        user_input: str,
    ) -> tuple[list[BaseMessage], ContextSnapshot]:
        history = history or []
        docs = retrieved_docs or []
        tools = tools or []
        role = getattr(user, "role", "guest")
        uid = getattr(user, "id", "anonymous")

        sections = [
            ContextSection("角色与硬性规则", persona.strip(), 1),
            ContextSection("用户身份", f"当前用户: {uid} / 角色: {role}。只能访问自己有权访问的数据。", 2),
            ContextSection("检索增强知识", self.format_docs(docs), 3),
            ContextSection("可用工具清单", self.format_tools(tools), 4),
        ]
        snapshot = ContextSnapshot(max_chars=self.max_chars)

        # Reserve room for the user turn and a few history turns.
        reserve = min(self.max_chars // 3, max(240, len(user_input) + 80))
        system_budget = max(320, self.max_chars - reserve)
        chosen: list[str] = []
        used = 0
        for section in sorted(sections, key=lambda s: s.priority):
            if not section.content:
                snapshot.sections.append({"name": section.name, "chars": 0, "included": False,
                                          "priority": section.priority})
                continue
            if used + section.chars <= system_budget:
                chosen.append(f"[{section.name}]\n{section.content}")
                used += section.chars
                snapshot.sections.append({"name": section.name, "chars": section.chars,
                                          "included": True, "priority": section.priority})
            else:
                remaining = system_budget - used
                if remaining > 80 and section.priority >= 3:
                    clipped = section.content[:remaining] + "…[已截断]"
                    chosen.append(f"[{section.name}]\n{clipped}")
                    used += len(clipped)
                    snapshot.sections.append({"name": section.name, "chars": len(clipped),
                                              "included": True, "truncated": True,
                                              "priority": section.priority})
                else:
                    snapshot.sections.append({"name": section.name, "chars": section.chars,
                                              "included": False, "priority": section.priority})

        system_text = "\n\n".join(chosen)
        compacted, dropped, compressed = self.compact(history, max(160, self.max_chars - used - len(user_input)))
        messages: list[BaseMessage] = [SystemMessage(content=system_text), *compacted,
                                       HumanMessage(content=user_input)]
        snapshot.total_chars = sum(len(str(m.content or "")) for m in messages)
        snapshot.kept_messages = len(compacted)
        snapshot.dropped_messages = dropped
        snapshot.compressed = compressed
        return messages, snapshot
