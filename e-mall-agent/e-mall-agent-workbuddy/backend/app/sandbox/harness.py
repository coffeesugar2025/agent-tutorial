"""Per-task isolated execution harness.

A Harness owns a trace id, the caller identity, a resource budget/deadline and
a tool namespace, and records every tool/code invocation so a task can be
audited with :meth:`close`.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .code_mode import CodeModeRunner, ToolNamespace, build_tool_namespace
from .executor import ExecutionResult
from .policy import SandboxPolicy


class HarnessBudgetExceeded(RuntimeError):
    """Raised when a harness budget or deadline is exhausted."""


@dataclass
class CallRecord:
    seq: int
    ts: float
    kind: str
    name: str
    input: Any
    output: Any = None
    ok: bool = True
    error: str = ""
    latency_ms: float = 0.0


@dataclass
class HarnessReport:
    trace_id: str
    user: Any
    calls: list[CallRecord] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def success_rate(self) -> float:
        if not self.calls:
            return 1.0
        return sum(1 for c in self.calls if c.ok) / len(self.calls)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user": self.user,
            "call_count": self.call_count,
            "success_rate": round(self.success_rate, 4),
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 3),
            "budget": dict(self.budget),
            "deadline_exceeded": bool(self.budget.get("deadline_exceeded", False)),
            "calls": [
                {
                    "seq": c.seq, "ts": round(c.ts, 6), "kind": c.kind,
                    "name": c.name, "input": c.input, "output": c.output,
                    "ok": c.ok, "error": c.error,
                    "latency_ms": round(c.latency_ms, 3),
                }
                for c in self.calls
            ],
        }


class Harness:
    """Isolated run context for one task."""

    def __init__(self, trace_id: str | None = None, user: Any = None,
                 budget: dict[str, Any] | None = None,
                 deadline: float | None = None,
                 tool_namespace: Any = None,
                 policy: SandboxPolicy | None = None,
                 runner: CodeModeRunner | None = None,
                 clock: Any = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.user = user
        self.budget = dict(budget or {})
        if deadline is not None:
            self.budget["deadline_seconds"] = deadline
        # 可注入单调时钟：生产默认 time.monotonic；测试注入可控时钟以避免
        # Windows 上 ~15ms 时钟分辨率导致的 deadline 断言偶发失败。
        self._clock = clock or time.monotonic
        self.started_at = self._clock()
        self.deadline_at = (
            self.started_at + float(deadline) if deadline is not None else None
        )
        self.tool_namespace = self._normalise_namespace(tool_namespace)
        self.runner = runner or CodeModeRunner(policy)
        self._records: list[CallRecord] = []
        self._closed = False

    @staticmethod
    def _normalise_namespace(tools: Any) -> ToolNamespace | None:
        if tools is None:
            return None
        if isinstance(tools, ToolNamespace):
            return tools
        return build_tool_namespace(tools)

    # ------------------------------------------------------------------ utils
    def _check_budget(self, kind: str) -> None:
        key = "max_tool_calls" if kind == "tool" else "max_code_runs"
        limit = self.budget.get(key)
        if limit is not None:
            used = sum(1 for c in self._records if c.kind == kind)
            if used >= int(limit):
                raise HarnessBudgetExceeded(f"{key} 超出预算 {limit}")
        if self.deadline_at is not None and self._clock() > self.deadline_at:
            self.budget["deadline_exceeded"] = True
            raise HarnessBudgetExceeded("任务已超过 deadline")

    def _record(self, kind: str, name: str, payload: Any, output: Any,
                ok: bool, error: str, started: float) -> CallRecord:
        record = CallRecord(
            seq=len(self._records) + 1, ts=time.time(), kind=kind, name=name,
            input=payload, output=output, ok=ok, error=error,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        self._records.append(record)
        return record

    # ------------------------------------------------------------------ public
    def record(self, event: str, payload: Any = None, output: Any = None,
               ok: bool = True, error: str = "") -> CallRecord:
        """Manually append an observation to the harness log."""
        return self._record("event", event, payload, output, ok, error,
                            time.perf_counter())

    def call_tool(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self._check_budget("tool")
        if self.tool_namespace is None or not hasattr(self.tool_namespace, name):
            raise KeyError(f"工具不存在: {name}")
        func = getattr(self.tool_namespace, name)
        started = time.perf_counter()
        try:
            output = func(*args, **kwargs)
            self._record("tool", name, {"args": args, "kwargs": kwargs},
                         output, True, "", started)
            return output
        except Exception as exc:  # noqa: BLE001 - recorded as a failed call
            self._record("tool", name, {"args": args, "kwargs": kwargs},
                         None, False, str(exc), started)
            raise

    def run_code(self, code: str) -> ExecutionResult:
        self._check_budget("code")
        namespace = self.tool_namespace if self.tool_namespace is not None else {}
        started = time.perf_counter()
        result = self.runner.run(code, namespace)
        self._record("code", "code_mode", code, result.as_dict(), result.ok,
                     result.error, started)
        return result

    def close(self) -> dict[str, Any]:
        """Finalise the harness and return a structured execution report."""
        if not self._closed:
            self._closed = True
        report = HarnessReport(
            trace_id=self.trace_id, user=self.user, calls=list(self._records),
            budget=dict(self.budget), started_at=self.started_at,
            finished_at=self._clock(),
        )
        return report.as_dict()

    @property
    def calls(self) -> list[CallRecord]:
        return list(self._records)

    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        # Keep the report accessible via ``close`` even on exceptions.
        return False


__all__ = [
    "Harness", "HarnessReport", "CallRecord", "HarnessBudgetExceeded",
]
