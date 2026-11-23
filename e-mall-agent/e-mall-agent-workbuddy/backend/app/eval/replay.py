"""Trace replay for bad-case reproduction and regression diffing."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

_TOOL_EVENTS = {"tool_call", "tool_result", "tool_start", "tool_end", "tool"}


@dataclass
class ReplayStep:
    seq: int
    ts: float
    node: str
    event: str
    tool: str
    payload: Any = None


@dataclass
class ReplayResult:
    trace_id: str = ""
    steps: list[ReplayStep] = field(default_factory=list)
    tool_sequence: list[str] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "tool_sequence": list(self.tool_sequence),
            "steps": [
                {"seq": s.seq, "ts": s.ts, "node": s.node, "event": s.event,
                 "tool": s.tool, "payload": s.payload}
                for s in self.steps
            ],
            "executions": self.executions,
        }


class ReplayRunner:
    """Extract and optionally re-execute tool calls from tracer events."""

    def __init__(self, executors: Mapping[str, Callable[..., Any]] | None = None) -> None:
        self.executors: dict[str, Callable[..., Any]] = dict(executors or {})

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self.executors[name] = fn

    @staticmethod
    def _events(trace_events: Any) -> list[dict[str, Any]]:
        if isinstance(trace_events, Mapping):
            trace_events = trace_events.get("events", [])
        return [dict(e) for e in (trace_events or [])]

    def replay(self, trace_events: Any, execute: bool = False) -> ReplayResult:
        events = sorted(self._events(trace_events), key=lambda e: e.get("ts", 0))
        trace_id = str(events[0].get("trace_id", "")) if events else ""
        result = ReplayResult(trace_id=trace_id)
        for event in events:
            payload = event.get("payload")
            tool = ""
            if isinstance(payload, Mapping):
                tool = str(payload.get("tool") or payload.get("name") or "")
            if not tool and event.get("event") in _TOOL_EVENTS:
                tool = str(event.get("node") or payload or "")
            if not tool:
                continue
            step = ReplayStep(
                seq=len(result.steps) + 1,
                ts=float(event.get("ts", 0)),
                node=str(event.get("node", "")),
                event=str(event.get("event", "")),
                tool=tool, payload=payload,
            )
            result.steps.append(step)
            result.tool_sequence.append(tool)

            if execute:
                record: dict[str, Any] = {"tool": tool, "ok": False,
                                          "result": None, "error": "", "latency_ms": 0.0}
                fn = self.executors.get(tool)
                started = time.perf_counter()
                if fn is None:
                    record["error"] = f"未注册工具: {tool}"
                else:
                    try:
                        args = payload.get("args", []) if isinstance(payload, Mapping) else []
                        kwargs = payload.get("kwargs", {}) if isinstance(payload, Mapping) else {}
                        record["result"] = fn(*(args or []), **(kwargs or {}))
                        record["ok"] = True
                    except Exception as exc:  # noqa: BLE001 - recorded, not raised
                        record["error"] = f"{type(exc).__name__}: {exc}"
                record["latency_ms"] = round(
                    (time.perf_counter() - started) * 1000, 3
                )
                result.executions.append(record)
        return result

    def diff(self, expected: Any, actual: Any) -> dict[str, Any]:
        """Compare two trace event lists by tool sequence and payload content."""
        left = self.replay(expected)
        right = self.replay(actual)
        lseq, rseq = left.tool_sequence, right.tool_sequence
        missing: list[str] = []
        extra: list[str] = []
        left_pool, right_pool = list(lseq), list(rseq)
        for tool in lseq:
            if tool in right_pool:
                right_pool.remove(tool)
            else:
                missing.append(tool)
        for tool in rseq:
            if tool in left_pool:
                left_pool.remove(tool)
            else:
                extra.append(tool)
        content_mismatches: list[dict[str, Any]] = []
        for index, (a, b) in enumerate(zip(left.steps, right.steps)):
            if a.tool != b.tool:
                content_mismatches.append({
                    "index": index, "expected": a.tool, "actual": b.tool,
                    "reason": "tool",
                })
            elif a.payload != b.payload:
                content_mismatches.append({
                    "index": index, "expected": a.payload, "actual": b.payload,
                    "reason": "payload",
                })
        matched = (lseq == rseq and not content_mismatches)
        return {
            "match": matched,
            "expected_sequence": lseq,
            "actual_sequence": rseq,
            "missing": missing,
            "extra": extra,
            "order_changed": lseq != rseq and not missing and not extra,
            "content_mismatches": content_mismatches,
        }


__all__ = ["ReplayRunner", "ReplayResult", "ReplayStep"]
