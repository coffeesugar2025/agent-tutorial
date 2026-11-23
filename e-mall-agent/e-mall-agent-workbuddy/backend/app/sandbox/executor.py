"""AST-validated, budgeted execution of untrusted Python snippets.

This is an in-process *soft* sandbox: it is strong enough to stop accidental or
naive hostile LLM output (imports, dunder escapes, eval/exec, runaway loops)
without spawning processes.  For a hard security boundary, run it inside a
separate restricted OS process/container.
"""
from __future__ import annotations

import ast
import builtins
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .policy import SandboxPolicy, SandboxViolation

_STEP_FN = "_ecom_sandbox_tick"
_RESULT_VAR = "__ecom_sandbox_result__"

# Names never allowed to appear in a Load context inside a snippet.
_FORBIDDEN_NAMES: frozenset[str] = frozenset({
    "__builtins__", "__import__", "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "object", "type", "help",
    "breakpoint", "memoryview", "eval", "exec", "compile", "open", "input",
    "exit", "quit",
})

_ALLOWED_DUNDERS: frozenset[str] = frozenset({"__name__", "__doc__"})

DEFAULT_BUILTIN_NAMES = frozenset({
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "divmod", "enumerate",
    "filter", "float", "frozenset", "hex", "int", "isinstance", "issubclass",
    "len", "list", "map", "max", "min", "oct", "ord", "pow", "range",
    "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
})


@dataclass
class ExecutionResult:
    """Outcome of one sandboxed execution."""

    ok: bool
    value: Any = None
    stdout: str = ""
    error: str = ""
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "stdout": self.stdout,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 3),
        }


class _SandboxTimeout(Exception):
    pass


class _SandboxStepLimit(Exception):
    pass


class _Budget:
    """Shared, monotonic step + wall-clock budget checked from loop bodies."""

    def __init__(self, policy: SandboxPolicy) -> None:
        self.deadline = time.monotonic() + policy.timeout_ms / 1000.0
        self.max_steps = policy.max_steps
        self.steps = 0

    def tick(self) -> None:
        self.steps += 1
        if self.steps > self.max_steps:
            raise _SandboxStepLimit(
                f"执行步数超过上限 {self.max_steps}"
            )
        if time.monotonic() > self.deadline:
            raise _SandboxTimeout("执行超时")


class _LimitedWriter:
    """StringIO-like sink that silently truncates at ``max_length`` chars."""

    def __init__(self, max_length: int) -> None:
        self.max_length = max_length
        self._parts: list[str] = []
        self.written = 0

    def write(self, text: str) -> int:
        text = str(text)
        self.written += len(text)
        remaining = self.max_length - sum(len(p) for p in self._parts)
        if remaining > 0:
            self._parts.append(text[:remaining])
        return len(text)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        return "".join(self._parts)


class _Validator(ast.NodeVisitor):
    """Static rejection of policy violations before any code is executed."""

    def __init__(self, policy: SandboxPolicy) -> None:
        self.policy = policy

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if not self.policy.allows_import(alias.name):
                raise SandboxViolation(f"禁止导入模块: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if not self.policy.allows_import(module):
            raise SandboxViolation(f"禁止导入模块: {module}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        attr = node.attr
        if attr in self.policy.forbidden_attrs:
            raise SandboxViolation(f"禁止访问属性: {attr}")
        if attr.startswith("__") and attr.endswith("__") and attr not in _ALLOWED_DUNDERS:
            raise SandboxViolation(f"禁止访问属性: {attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in _FORBIDDEN_NAMES:
            raise SandboxViolation(f"禁止使用名称: {node.id}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.policy.forbidden_calls:
            raise SandboxViolation(f"禁止调用函数: {func.id}")
        self.generic_visit(node)


class _Instrumenter(ast.NodeTransformer):
    """Insert one budget tick at the start of every suite (incl. loop bodies)."""

    _SUITE_FIELDS = ("body", "orelse", "finalbody")

    def _tick(self) -> ast.Expr:
        return ast.Expr(value=ast.Call(
            func=ast.Name(id=_STEP_FN, ctx=ast.Load()), args=[], keywords=[]
        ))

    def _inject(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if not body:
            return body
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Name)
                and first.value.func.id == _STEP_FN):
            return body
        return [self._tick(), *body]

    def generic_visit(self, node: ast.AST) -> ast.AST:
        for field, value in ast.iter_fields(node):
            if field in self._SUITE_FIELDS and isinstance(value, list) \
                    and all(isinstance(item, ast.stmt) for item in value):
                setattr(node, field, self._inject(value))
        return super().generic_visit(node)


class CodeSandbox:
    """Execute short Python snippets under a :class:`SandboxPolicy`."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

    @staticmethod
    def validate(code: str, policy: SandboxPolicy | None = None) -> ast.Module:
        """Parse and statically validate ``code``; raise on any violation."""
        p = policy or SandboxPolicy()
        tree = ast.parse(code)
        _Validator(p).visit(tree)
        return tree

    @staticmethod
    def _build_builtins(writer: _LimitedWriter) -> dict[str, Any]:
        names: dict[str, Any] = {
            name: getattr(builtins, name)
            for name in DEFAULT_BUILTIN_NAMES
            if hasattr(builtins, name)
        }

        def _print(*args: Any, sep: str = " ", end: str = "\n") -> None:
            writer.write(sep.join(str(a) for a in args) + end)

        names["print"] = _print
        return names

    def run(self, code: str, namespace: Mapping[str, Any] | None = None,
            variable_name: str = "tools") -> ExecutionResult:
        """Run ``code`` and capture stdout/value.

        ``namespace`` is exposed under ``variable_name`` (default ``tools``).
        The value of the final expression, or a variable named ``result``, is
        returned in :attr:`ExecutionResult.value`.
        """
        started = time.perf_counter()
        writer = _LimitedWriter(self.policy.max_output_length)
        try:
            tree = self.validate(code, self.policy)
            self._promote_last_expr(tree)
            tree = _Instrumenter().visit(tree)
            ast.fix_missing_locations(tree)
            compiled = compile(tree, "<sandbox>", "exec")
        except SandboxViolation as exc:
            return ExecutionResult(False, error=f"策略违规: {exc}",
                                   stdout=writer.getvalue(),
                                   duration_ms=(time.perf_counter() - started) * 1000)
        except (SyntaxError, ValueError) as exc:
            return ExecutionResult(False, error=f"语法错误: {exc}",
                                   stdout=writer.getvalue(),
                                   duration_ms=(time.perf_counter() - started) * 1000)

        budget = _Budget(self.policy)
        scope: dict[str, Any] = {
            "__builtins__": self._build_builtins(writer),
            _STEP_FN: budget.tick,
        }
        if namespace is not None:
            # Pass through as-is: mappings support ``tools["name"]`` while
            # module-like objects support ``tools.name(...`` (Code Mode).
            scope[variable_name] = namespace

        error = ""
        try:
            exec(compiled, scope, scope)  # noqa: S102 - validated + restricted
        except _SandboxTimeout as exc:
            error = f"执行超时: {exc}"
        except _SandboxStepLimit as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - surface snippet failures
            error = f"{type(exc).__name__}: {exc}"

        value = scope.get("result", _MISSING)
        if value is _MISSING:
            value = scope.get(_RESULT_VAR)
        if value is _MISSING:
            value = None

        return ExecutionResult(
            ok=not error,
            value=value,
            stdout=writer.getvalue(),
            error=error,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _promote_last_expr(tree: ast.Module) -> None:
        """Turn a trailing expression into a result assignment."""
        if not tree.body:
            return
        last = tree.body[-1]
        if isinstance(last, ast.Expr):
            tree.body[-1] = ast.Assign(
                targets=[ast.Name(id=_RESULT_VAR, ctx=ast.Store())],
                value=last.value,
            )


_MISSING = object()


# Re-export for convenience within the package.
__all__ = ["CodeSandbox", "ExecutionResult", "SandboxViolation", "SandboxPolicy"]
