"""Declarative security policy for the in-process Python code sandbox.

The policy is a plain dataclass so it can be persisted / replaced without
touching the executor.  All defaults are deliberately conservative.
"""
from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_FORBIDDEN_IMPORTS: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "socket", "shutil", "ctypes", "signal",
    "multiprocessing", "threading", "asyncio", "importlib", "builtins",
    "marshal", "pickle", "code", "codeop", "runpy", "tempfile", "pathlib",
    "io", "webbrowser", "commands", "pty", "fcntl", "resource", "platform",
})

DEFAULT_FORBIDDEN_ATTRS: frozenset[str] = frozenset({
    "__class__", "__globals__", "__builtins__", "__subclasses__", "__mro__",
    "__bases__", "__dict__", "__code__", "__closure__", "__func__",
    "__getattribute__", "__setattr__", "__delattr__", "__reduce__",
    "__reduce_ex__", "__init_subclass__", "__import__", "open", "eval",
    "exec", "compile", "input", "exit", "quit",
})

DEFAULT_FORBIDDEN_CALLS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "open", "input", "__import__", "exit", "quit",
})

DEFAULT_ALLOWED_BUILTINS: frozenset[str] = frozenset({
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "divmod", "enumerate",
    "filter", "float", "frozenset", "hex", "int", "isinstance", "issubclass",
    "len", "list", "map", "max", "min", "oct", "ord", "pow", "print", "range",
    "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
})


class SandboxViolation(Exception):
    """Raised by static validation when code breaks the policy."""


@dataclass(frozen=True)
class SandboxPolicy:
    """Limits applied to every code fragment executed by :class:`CodeSandbox`."""

    forbidden_imports: frozenset[str] = DEFAULT_FORBIDDEN_IMPORTS
    forbidden_attrs: frozenset[str] = DEFAULT_FORBIDDEN_ATTRS
    forbidden_calls: frozenset[str] = DEFAULT_FORBIDDEN_CALLS
    allowed_builtins: frozenset[str] = DEFAULT_ALLOWED_BUILTINS
    max_steps: int = 10_000
    max_output_length: int = 4096
    timeout_ms: int = 1000
    allowed_imports: frozenset[str] = field(default_factory=frozenset)

    def allows_import(self, module: str) -> bool:
        root = (module or "").split(".", 1)[0]
        if root in self.allowed_imports:
            return True
        return root not in self.forbidden_imports
