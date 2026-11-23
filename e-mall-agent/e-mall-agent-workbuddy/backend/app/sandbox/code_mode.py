"""Code Mode: let a model orchestrate existing tools with generated Python.

The generated snippet receives a module-like ``tools`` object (see
:func:`build_tool_namespace`) and executes inside :class:`CodeSandbox`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .executor import CodeSandbox, ExecutionResult
from .policy import SandboxPolicy


@dataclass
class ToolCallRecord:
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    result: Any = None
    ok: bool = True
    error: str = ""
    latency_ms: float = 0.0


class ToolNamespace:
    """Module-like facade over a set of callables, with call recording."""

    def __init__(self, tools: Mapping[str, Callable[..., Any]]) -> None:
        self._tools = dict(tools)
        self.calls: list[ToolCallRecord] = []
        for name, func in self._tools.items():
            setattr(self, name, self._wrap(name, func))

    def _wrap(self, name: str, func: Callable[..., Any]) -> Callable[..., Any]:
        def _call(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            record = ToolCallRecord(name=name, args=args, kwargs=dict(kwargs))
            try:
                record.result = func(*args, **kwargs)
                return record.result
            except Exception as exc:  # noqa: BLE001 - recorded, then propagated
                record.ok = False
                record.error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                record.latency_ms = (time.perf_counter() - started) * 1000
                self.calls.append(record)

        _call.__name__ = name
        return _call

    def names(self) -> list[str]:
        return sorted(self._tools)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tools": self.names(),
            "calls": [
                {
                    "name": c.name, "args": list(c.args), "kwargs": c.kwargs,
                    "ok": c.ok, "error": c.error,
                    "latency_ms": round(c.latency_ms, 3),
                }
                for c in self.calls
            ],
        }


def build_tool_namespace(tools: Any) -> ToolNamespace:
    """Normalise a tool collection into a callable ``tools.*`` namespace.

    Accepted inputs: ``{name: func}`` mappings, an iterable of callables, or an
    iterable of objects exposing ``name`` plus ``func``/``run``/``__call__``.
    """
    resolved: dict[str, Callable[..., Any]] = {}
    if isinstance(tools, Mapping):
        for name, func in tools.items():
            if not callable(func):
                raise TypeError(f"工具 {name!r} 不可调用")
            resolved[str(name)] = func
        return ToolNamespace(resolved)

    if isinstance(tools, Iterable) and not isinstance(tools, (str, bytes)):
        for item in tools:
            if callable(item) and not hasattr(item, "name"):
                resolved[getattr(item, "__name__", type(item).__name__)] = item
                continue
            name = getattr(item, "name", None)
            func = getattr(item, "func", None) or getattr(item, "run", None)
            if func is None and callable(item):
                func = item
            if not name or not callable(func):
                raise TypeError(f"无法解析工具: {item!r}")
            resolved[str(name)] = func
        return ToolNamespace(resolved)

    raise TypeError("tools 必须是映射或可迭代的工具集合")


class CodeModeRunner:
    """Compile and execute a Code Mode orchestration snippet."""

    def __init__(self, policy: SandboxPolicy | None = None,
                 sandbox: CodeSandbox | None = None) -> None:
        self.sandbox = sandbox or CodeSandbox(policy)

    def build_tool_namespace(self, tools: Any) -> ToolNamespace:
        return build_tool_namespace(tools)

    def run(self, code: str, namespace: Any = None,
            tools: Any = None) -> ExecutionResult:
        """Execute ``code`` with ``namespace`` (or freshly built ``tools``)."""
        if namespace is None and tools is not None:
            namespace = build_tool_namespace(tools)
        if namespace is None:
            namespace = {}
        return self.sandbox.run(code, namespace)


__all__ = [
    "CodeModeRunner", "ToolNamespace", "ToolCallRecord", "build_tool_namespace",
]
