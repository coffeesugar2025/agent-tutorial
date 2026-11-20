"""最小可用的链路追踪（Trace）。

生产环境常用 OpenTelemetry / LangSmith / Langfuse。本教程用一个 80 行的实现，
让你先理解 Trace 的本质：一次请求是一棵树，节点叫 Span，节点上记着耗时、状态和属性。
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Span:
    name: str
    attrs: dict[str, Any] = field(default_factory=dict)
    start: float = field(default_factory=time.perf_counter)
    end: float | None = None
    status: str = "ok"
    events: list[dict] = field(default_factory=list)
    children: list["Span"] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return round(((self.end or time.perf_counter()) - self.start) * 1000, 2)


class Tracer:
    """记录一次 Agent 运行的全部关键节点。"""

    def __init__(self, name: str = "agent-run"):
        self.trace_id = uuid.uuid4().hex[:12]
        self.name = name
        self.root = Span(name)
        self._stack: list[Span] = [self.root]
        self.metrics: dict[str, float] = {
            "llm_calls": 0,
            "tool_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "errors": 0,
        }
        self.tool_timeline: list[dict] = []

    @property
    def current(self) -> Span:
        return self._stack[-1]

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Span]:
        span = Span(name, attrs)
        self.current.children.append(span)
        self._stack.append(span)
        try:
            yield span
        except Exception as exc:  # noqa: BLE001 - 教程中需要记录所有异常
            span.status = "error"
            span.attrs["error"] = f"{type(exc).__name__}: {exc}"
            self.metrics["errors"] += 1
            raise
        finally:
            span.end = time.perf_counter()
            self._stack.pop()

    def event(self, name: str, **attrs: Any) -> None:
        self.current.events.append({"name": name, "at_ms": self.root.duration_ms, **attrs})

    def record_llm(self, response: Any) -> None:
        self.metrics["llm_calls"] += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.metrics["prompt_tokens"] += getattr(usage, "prompt_tokens", 0)
            self.metrics["completion_tokens"] += getattr(usage, "completion_tokens", 0)
        self.event(
            "llm_call",
            model=getattr(response, "model", "unknown"),
            tool_calls=[call.name for call in getattr(response, "tool_calls", [])],
        )

    def record_tool(self, name: str, args: dict, ok: bool, duration_ms: float, result: Any = None) -> None:
        self.metrics["tool_calls"] += 1
        if not ok:
            self.metrics["errors"] += 1
        self.tool_timeline.append(
            {
                "tool": name,
                "args": args,
                "ok": ok,
                "duration_ms": round(duration_ms, 2),
                "result_preview": str(result)[:160],
            }
        )
        self.event("tool_call", tool=name, ok=ok, duration_ms=round(duration_ms, 2))

    def summary(self) -> dict:
        spans: list[dict] = []

        def walk(span: Span, depth: int) -> None:
            spans.append(
                {
                    "name": span.name,
                    "depth": depth,
                    "duration_ms": span.duration_ms,
                    "status": span.status,
                    "attrs": span.attrs,
                }
            )
            for child in span.children:
                walk(child, depth + 1)

        self.root.end = self.root.end or time.perf_counter()
        walk(self.root, 0)
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "duration_ms": self.root.duration_ms,
            "metrics": dict(self.metrics),
            "tokens": self.metrics["prompt_tokens"] + self.metrics["completion_tokens"],
            "spans": spans,
            "tools": self.tool_timeline,
        }

    def print_tree(self) -> None:
        """在终端打印一棵可读的调用树。"""
        print(f"\nTRACE {self.trace_id}  {self.name}  {self.root.duration_ms:.0f}ms")

        def walk(span: Span, depth: int) -> None:
            icon = "x" if span.status == "error" else "-"
            print(f"{'  ' * depth}{icon} {span.name} ({span.duration_ms:.0f}ms) {span.attrs or ''}")
            for event in span.events:
                print(f"{'  ' * (depth + 1)}· {event['name']} {event.get('tool', '')}")
            for child in span.children:
                walk(child, depth + 1)

        walk(self.root, 0)
        print(
            f"  llm={self.metrics['llm_calls']} tool={self.metrics['tool_calls']} "
            f"token={self.metrics['prompt_tokens'] + self.metrics['completion_tokens']} "
            f"error={self.metrics['errors']}"
        )
