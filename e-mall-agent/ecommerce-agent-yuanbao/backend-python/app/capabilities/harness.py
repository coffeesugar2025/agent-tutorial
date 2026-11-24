"""Sandbox / Harness / Code Mode / 长任务恢复。

  sandbox_eval      AST 白名单受限表达式执行（禁 import / 属性 / 赋值 / 循环 / 任意调用）
  CodeMode          把「让模型写代码算」变成受控能力：表达式可审计、结果可校验
  LongTaskRunner    步骤级 checkpoint、心跳、失败后从断点 resume（不重跑已完成步骤）

边界说明：这是应用层的轻量沙盒（表达式级），不是 OS 级隔离。真正执行不可信代码
仍需容器 / gVisor / Firecracker / 独立进程 + seccomp；本模块明确标注该边界。
"""
from __future__ import annotations

import ast
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Call, ast.IfExp,
    ast.keyword, ast.Index if hasattr(ast, "Index") else ast.Load,
)
_ALLOWED_FUNCS = {"abs": abs, "min": min, "max": max, "round": round,
                  "len": len, "sum": sum, "int": int, "float": float}

MAX_NODES = 80
MAX_STRING = 200


class SandboxViolation(ValueError):
    pass


def validate_expression(expr: str) -> ast.Expression:
    """静态校验：节点类型、数量、函数名、字符串长度全部受限。"""
    if not isinstance(expr, str) or len(expr) > 1000:
        raise SandboxViolation("表达式为空或过长")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise SandboxViolation(f"语法错误：{exc}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise SandboxViolation(f"节点数 {len(nodes)} 超过上限 {MAX_NODES}")
    for node in nodes:
        if not isinstance(node, _ALLOWED_NODES):
            raise SandboxViolation(f"禁止的语法节点：{type(node).__name__}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and len(node.value) > MAX_STRING:
            raise SandboxViolation("字符串常量过长")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                raise SandboxViolation("仅允许白名单函数调用")
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            raise SandboxViolation("禁止赋值")
    return tree


def sandbox_eval(expr: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行受限表达式，返回结构化结果（含 AST 校验信息，便于审计）。"""
    started = time.perf_counter()
    try:
        tree = validate_expression(expr)
        env: dict[str, Any] = {"__builtins__": {}}
        env.update(_ALLOWED_FUNCS)
        env.update(context or {})
        value = eval(compile(tree, "<sandbox>", "eval"), env, {})  # noqa: S307 - 已做 AST 白名单
        return {"ok": True, "expression": expr, "value": value,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "sandbox": "ast-whitelist + empty-builtins"}
    except SandboxViolation as exc:
        return {"ok": False, "expression": expr, "error": str(exc),
                "violation": True, "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {"ok": False, "expression": expr,
                "error": f"{type(exc).__name__}: {exc}", "violation": False,
                "elapsed_ms": int((time.perf_counter() - started) * 1000)}


# ---------------------------------------------------------------- Code Mode
CODE_TEMPLATES: dict[str, str] = {
    "到手价": "round({subtotal} - {discount}, 2)",
    "折扣封顶": "min({raw_discount}, {cap})",
    "总价": "round({price} * {quantity}, 2)",
    "库存校验": "max(0, {stock} - {quantity})",
}


class CodeMode:
    """把自然语言计算意图映射到受限表达式，执行后与领域函数结果交叉校验。"""

    @staticmethod
    def compile_task(intent: str, params: dict[str, Any]) -> dict[str, Any]:
        tpl = CODE_TEMPLATES.get(intent)
        if not tpl:
            return {"ok": False, "error": f"未知计算意图：{intent}",
                    "available": list(CODE_TEMPLATES)}
        expr = tpl.format(**params)
        result = sandbox_eval(expr)
        result["intent"] = intent
        result["params"] = params
        return result

    @staticmethod
    def verify_price(subtotal: float, discount: float, expected: float) -> dict[str, Any]:
        res = CodeMode.compile_task("到手价", {"subtotal": subtotal, "discount": discount})
        res["expected"] = expected
        res["match"] = bool(res.get("ok")) and abs(float(res["value"]) - expected) < 1e-6
        return res


# ---------------------------------------------------------------- 长任务恢复
@dataclass
class Checkpoint:
    task_id: str
    steps_total: int
    completed: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"          # running / paused / done / failed
    heartbeat: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "steps_total": self.steps_total,
                "completed": self.completed, "results": self.results,
                "status": self.status, "heartbeat": self.heartbeat,
                "created_at": self.created_at, "error": self.error,
                "resume_from": len(self.completed)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        cp = cls(task_id=data["task_id"], steps_total=data["steps_total"])
        cp.completed = list(data.get("completed", []))
        cp.results = list(data.get("results", []))
        cp.status = data.get("status", "running")
        cp.heartbeat = data.get("heartbeat", time.time())
        cp.created_at = data.get("created_at", time.time())
        cp.error = data.get("error", "")
        return cp


StepFn = Callable[[], dict[str, Any]]


class LongTaskRunner:
    """步骤级 checkpoint：失败/暂停后 resume 只跑未完成步骤，已完成结果不重算。"""

    def __init__(self) -> None:
        self._store: dict[str, Checkpoint] = {}

    def save(self, cp: Checkpoint) -> None:
        cp.heartbeat = time.time()
        self._store[cp.task_id] = cp

    def load(self, task_id: str) -> Checkpoint | None:
        return self._store.get(task_id)

    def start(self, steps: list[tuple[str, StepFn]],
              task_id: str | None = None, fail_at: int | None = None) -> dict[str, Any]:
        tid = task_id or "task_" + uuid.uuid4().hex[:10]
        cp = Checkpoint(task_id=tid, steps_total=len(steps))
        self.save(cp)
        return self._execute(steps, cp, fail_at=fail_at, resumed=False)

    def resume(self, task_id: str, steps: list[tuple[str, StepFn]]) -> dict[str, Any]:
        cp = self.load(task_id)
        if cp is None:
            raise KeyError(f"长任务不存在：{task_id}")
        if cp.status == "done":
            return {"task_id": task_id, "status": "already_done",
                    "resumed": False, "checkpoint": cp.to_dict()}
        return self._execute(steps, cp, fail_at=None, resumed=True)

    def _execute(self, steps: list[tuple[str, StepFn]], cp: Checkpoint,
                 fail_at: int | None, resumed: bool) -> dict[str, Any]:
        start = len(cp.completed)
        for i in range(start, len(steps)):
            name, fn = steps[i]
            if fail_at is not None and i == fail_at:
                cp.status = "paused"
                cp.error = f"模拟在步骤 {i} 中断（fail_at={fail_at}）"
                self.save(cp)
                return {"task_id": cp.task_id, "status": "paused", "resumed": resumed,
                        "checkpoint": cp.to_dict()}
            try:
                res = fn()
            except Exception as exc:
                cp.status = "failed"
                cp.error = f"{type(exc).__name__}: {exc}"
                self.save(cp)
                return {"task_id": cp.task_id, "status": "failed", "resumed": resumed,
                        "checkpoint": cp.to_dict()}
            cp.completed.append(name)
            cp.results.append({"step": name, "result": res})
            self.save(cp)
        cp.status = "done"
        self.save(cp)
        return {"task_id": cp.task_id, "status": "done", "resumed": resumed,
                "reused_steps": start, "checkpoint": cp.to_dict()}

    def stats(self) -> dict[str, Any]:
        return {"tasks": len(self._store),
                "statuses": {s: sum(1 for c in self._store.values() if c.status == s)
                             for s in ("running", "paused", "done", "failed")}}


RUNNER = LongTaskRunner()


def harness_spec() -> dict[str, Any]:
    return {
        "sandbox": "AST 白名单表达式级（非 OS 隔离；不可信代码仍需容器/gVisor/seccomp）",
        "code_mode": "意图→受限表达式模板→沙盒执行→与领域函数结果交叉校验",
        "long_task": "步骤级 checkpoint + heartbeat + resume（不重跑已完成步骤）",
        "allowed_ast_nodes": [n.__name__ for n in dict.fromkeys(_ALLOWED_NODES)],
        "allowed_functions": sorted(_ALLOWED_FUNCS),
    }
