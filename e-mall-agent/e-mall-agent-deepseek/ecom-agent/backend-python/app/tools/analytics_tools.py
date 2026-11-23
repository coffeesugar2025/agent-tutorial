"""运营类工具：text2sql（只读、表白名单、注入防护）与 run_python（沙箱子进程）。

text2sql 三道闸门：
1. **生成约束**：优先用确定性模板（覆盖率高的常见经营问题），不把自然语言直接拼 SQL；
2. **静态校验**：只允许单条 SELECT、表白名单、禁注释/多语句/写操作/系统库/UNION；
3. **执行约束**：强制 LIMIT ≤ ``TEXT2SQL_MAX_ROWS``，只读连接语义（不提交事务）。

run_python：AST 白名单校验 + ``python -I`` 子进程隔离 + 超时 + 最小环境变量。
明确边界：这是"沙箱 Lite"，不是安全容器；生产若需强隔离应换 gVisor/Firecracker。
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

from pydantic import Field
from sqlalchemy import text

from app.common.envelope import CamelModel
from app.common.errors import param_invalid
from app.config import settings
from app.infra.db import session_scope
from app.tools.base import Risk, ToolContext, ToolSpec

logger = logging.getLogger(__name__)

ALLOWED_TABLES: dict[str, set[str]] = {
    "order_info": {
        "id", "order_no", "user_id", "status", "total_amount", "pay_amount",
        "created_at", "paid_at", "shipped_at", "finished_at",
    },
    "order_item": {"id", "order_id", "product_id", "sku", "title", "price", "quantity"},
    "product": {
        "id", "sku", "title", "brand", "category_id", "price", "stock", "status",
        "rating", "sales", "created_at",
    },
    "category": {"id", "name", "parent_id"},
    "refund_request": {"id", "refund_no", "order_id", "user_id", "amount", "status", "created_at"},
    "llm_call": {
        "id", "provider", "model", "prompt_tokens", "completion_tokens", "cached_tokens",
        "cost_cents", "latency_ms", "status", "created_at",
    },
}
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke",
    "replace", "into", "outfile", "dumpfile", "load_file", "sleep", "benchmark",
    "information_schema", "performance_schema", "mysql", "sys", "union", "handler",
    "procedure", "call", "execute", "prepare", "lock", "share",
}
TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)
LIMIT_RE = re.compile(r"\blimit\s+(\d+)", re.IGNORECASE)


class Text2SqlArgs(CamelModel):
    question: str = Field(min_length=2, max_length=300, description="经营分析问题，如“最近7天销售额趋势”")


class RunPythonArgs(CamelModel):
    code: str = Field(min_length=1, max_length=4000, description="要执行的 Python 片段")
    purpose: str | None = Field(default=None, max_length=200, description="这次计算的目的")


# ---------------------------------------------------------------------------
# SQL 生成（模板，确定性）
# ---------------------------------------------------------------------------
def generate_sql(question: str) -> str:
    """把常见经营问题映射为白名单内的只读 SQL。"""
    text_q = (question or "").lower()
    if any(word in question for word in ("销售额", "营收", "gmv", "GMV", "成交额", "金额趋势")):
        return (
            "SELECT DATE(created_at) AS day, COUNT(*) AS order_count, "
            "ROUND(SUM(pay_amount), 2) AS gmv FROM order_info "
            "WHERE status NOT IN ('CANCELLED') GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 30"
        )
    if any(word in question for word in ("客单价", "平均订单")):
        return (
            "SELECT ROUND(AVG(pay_amount), 2) AS avg_order_amount, COUNT(*) AS order_count "
            "FROM order_info WHERE status NOT IN ('CANCELLED')"
        )
    if any(word in question for word in ("热销", "销量最好", "卖得最好", "top", "TOP", "爆款")):
        return (
            "SELECT oi.sku, oi.title, SUM(oi.quantity) AS total_qty, "
            "ROUND(SUM(oi.price * oi.quantity), 2) AS total_amount "
            "FROM order_item oi GROUP BY oi.sku, oi.title ORDER BY total_qty DESC LIMIT 10"
        )
    if any(word in question for word in ("退款", "退货")):
        return (
            "SELECT status, COUNT(*) AS cnt, ROUND(SUM(amount), 2) AS amount "
            "FROM refund_request GROUP BY status ORDER BY cnt DESC LIMIT 20"
        )
    if any(word in question for word in ("模型", "token", "成本", "费用")):
        return (
            "SELECT model, COUNT(*) AS calls, SUM(prompt_tokens) AS prompt_tokens, "
            "SUM(completion_tokens) AS completion_tokens, SUM(cost_cents) AS cost_cents "
            "FROM llm_call GROUP BY model ORDER BY cost_cents DESC LIMIT 20"
        )
    if any(word in question for word in ("库存", "缺货", "stock")):
        return (
            "SELECT sku, title, stock, sales FROM product WHERE status = 1 "
            "ORDER BY stock ASC, sales DESC LIMIT 20"
        )
    if any(word in question for word in ("状态分布", "订单状态", "各状态")):
        return (
            "SELECT status, COUNT(*) AS cnt FROM order_info GROUP BY status ORDER BY cnt DESC LIMIT 20"
        )
    return (
        "SELECT DATE(created_at) AS day, COUNT(*) AS order_count "
        "FROM order_info GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 14"
    )


def validate_sql(sql: str, max_rows: int | None = None) -> str:
    """静态校验 SQL，返回可安全执行（已强制 LIMIT）的语句。"""
    raw = (sql or "").strip()
    if not raw:
        raise param_invalid("SQL 不能为空")
    if not re.match(r"^(select)\b", raw, flags=re.IGNORECASE):
        raise param_invalid("只允许执行 SELECT 查询")
    if "--" in raw or "/*" in raw or "#" in raw:
        raise param_invalid("SQL 中不允许出现注释")
    body = raw.rstrip(";").strip()
    if ";" in body:
        raise param_invalid("不允许多语句执行")
    lowered = body.lower()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise param_invalid(f"SQL 包含被禁止的关键字: {keyword}")
    tables = {match.group(1).lower() for match in TABLE_REF_RE.finditer(body)}
    if not tables:
        raise param_invalid("SQL 未引用任何白名单表")
    illegal = tables - set(ALLOWED_TABLES)
    if illegal:
        raise param_invalid(f"表不在白名单内: {sorted(illegal)}")
    limit_cap = max_rows or settings.text2sql_max_rows
    match = LIMIT_RE.search(body)
    if match:
        if int(match.group(1)) > limit_cap:
            body = LIMIT_RE.sub(f"LIMIT {limit_cap}", body, count=1)
    else:
        body = f"{body} LIMIT {limit_cap}"
    return body


def _jsonable(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def text2sql(ctx: ToolContext, question: str) -> dict[str, Any]:
    """自然语言 → 只读 SQL → 执行 → 结构化结果。"""
    sql = validate_sql(generate_sql(question))
    started = time.perf_counter()
    try:
        with session_scope() as db:
            result = db.execute(text(sql))
            rows = [dict(row) for row in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("text2sql 执行失败 sql=%s err=%s", sql, exc)
        return {"ok": False, "sql": sql, "rows": [], "error": f"查询执行失败: {exc}"}
    latency = int((time.perf_counter() - started) * 1000)
    columns = list(rows[0].keys()) if rows else []
    return {
        "ok": True,
        "sql": sql,
        "columns": columns,
        "rows": [{k: _jsonable(v) for k, v in row.items()} for row in rows],
        "rowCount": len(rows),
        "latencyMs": latency,
        "strategy": "template",
    }


# ---------------------------------------------------------------------------
# run_python 沙箱
# ---------------------------------------------------------------------------
FORBIDDEN_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Global,
    ast.Nonlocal,
    ast.ClassDef,
    ast.Delete,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
    ast.AsyncFunctionDef,
    ast.Raise,
)
FORBIDDEN_NAMES = {
    "eval", "exec", "open", "compile", "input", "globals", "locals", "vars",
    "__import__", "getattr", "setattr", "delattr", "memoryview", "object",
    "breakpoint", "help", "exit", "quit",
}
RUNNER = r"""
import contextlib, io, json, sys

src = sys.stdin.read()
safe_builtins = {
    name: __builtins__[name] for name in (
        "abs","all","any","bool","dict","divmod","enumerate","filter","float","format","int",
        "len","list","map","max","min","pow","print","range","reversed","round","set","sorted",
        "str","sum","tuple","zip","Exception","ValueError","TypeError","KeyError","IndexError",
        "True","False","None","min","max","sum","round","sorted"
    ) if name in __builtins__
}
buf = io.StringIO()
globals_dict = {"__builtins__": safe_builtins, "__name__": "__sandbox__"}
try:
    with contextlib.redirect_stdout(buf):
        exec(compile(src, "<sandbox>", "exec"), globals_dict)
except Exception as exc:
    sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", "stdout": buf.getvalue()}))
else:
    exported = {}
    for key, value in globals_dict.items():
        if key.startswith("_") or callable(value):
            continue
        try:
            json.dumps(value)
            exported[key] = value
        except Exception:
            exported[key] = repr(value)
    sys.stdout.write(json.dumps({"ok": True, "stdout": buf.getvalue(), "vars": exported}))
"""


def validate_python(code: str) -> ast.Module:
    """AST 白名单校验，拒绝导入/文件/网络/反射/异步等危险节点。"""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise param_invalid(f"代码语法错误: {exc.msg}") from exc
    if len(tree.body) > 120:
        raise param_invalid("代码块过大，请拆分")
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_NODES):
            raise param_invalid(f"不允许使用语法: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise param_invalid("不允许访问下划线/魔法属性")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise param_invalid(f"不允许使用函数: {node.id}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_NAMES:
                raise param_invalid(f"不允许调用: {func.id}")
    return tree


def run_python(ctx: ToolContext, code: str, purpose: str | None = None) -> dict[str, Any]:
    """在隔离子进程中执行计算型代码片段。"""
    validate_python(code)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="ecom_sandbox_") as workdir:
        try:
            completed = subprocess.run(  # noqa: S603 - 参数固定，无 shell
                [sys.executable, "-I", "-S", "-c", RUNNER],
                input=code,
                capture_output=True,
                text=True,
                timeout=settings.python_sandbox_timeout,
                cwd=workdir,
                env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"执行超时（>{settings.python_sandbox_timeout}s）",
                "latencyMs": int((time.perf_counter() - started) * 1000),
            }
    latency = int((time.perf_counter() - started) * 1000)
    stdout = (completed.stdout or "").strip()
    if not stdout:
        return {
            "ok": False,
            "error": (completed.stderr or "沙箱未返回结果").strip()[:500],
            "latencyMs": latency,
            "purpose": purpose,
        }
    try:
        parsed = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": True, "stdout": stdout[:4000], "vars": {}, "latencyMs": latency, "purpose": purpose}
    parsed["latencyMs"] = latency
    parsed["purpose"] = purpose
    return parsed


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
TEXT2SQL = ToolSpec(
    name="text2sql",
    description="把经营问题转换成只读 SQL 并执行（表/字段白名单，强制 LIMIT，禁止写操作）。",
    func=text2sql,
    risk=Risk.READ,
    args_model=Text2SqlArgs,
    timeout_seconds=12,
    max_retries=1,
    summarize=lambda data: (
        f"查询返回 {data.get('rowCount', 0)} 行" if data.get("ok") else data.get("error", "查询失败")
    ),
)

RUN_PYTHON = ToolSpec(
    name="run_python",
    description="在受限沙箱中执行计算型 Python 代码（禁用导入与文件/网络访问），返回 stdout 与变量。",
    func=run_python,
    risk=Risk.READ,
    args_model=RunPythonArgs,
    timeout_seconds=float(settings.python_sandbox_timeout + 5),
    max_retries=0,
    summarize=lambda data: (
        f"执行成功，输出 {len(str(data.get('stdout', '')))} 字符"
        if data.get("ok")
        else data.get("error", "执行失败")
    ),
)

__all__ = [
    "ALLOWED_TABLES",
    "RUN_PYTHON",
    "TEXT2SQL",
    "generate_sql",
    "run_python",
    "text2sql",
    "validate_python",
    "validate_sql",
]
