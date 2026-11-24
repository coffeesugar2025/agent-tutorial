"""请求/日志上下文变量：trace_id 贯穿日志、响应信封与 agent_trace。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议  |  [CAP-14] 可靠性/降级  （支撑）
# 职责：请求/日志上下文变量：trace_id 贯穿日志、响应信封与 agent_trace
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
span_id_var: ContextVar[str] = ContextVar("span_id", default="")
session_id_var: ContextVar[int | None] = ContextVar("session_id", default=None)
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)
agent_type_var: ContextVar[str] = ContextVar("agent_type", default="")


def get_trace_id() -> str:
    return trace_id_var.get()


def set_trace_id(value: str) -> None:
    trace_id_var.set(value)


def get_span_id() -> str:
    return span_id_var.get()


def set_span_id(value: str) -> None:
    span_id_var.set(value)


def get_session_id() -> int | None:
    return session_id_var.get()


def set_session_id(value: int | None) -> None:
    session_id_var.set(value)


def get_user_id() -> int | None:
    return user_id_var.get()


def set_user_id(value: int | None) -> None:
    user_id_var.set(value)


def set_agent_type(value: str) -> None:
    agent_type_var.set(value)


def get_agent_type() -> str:
    return agent_type_var.get()


__all__ = [
    "agent_type_var",
    "get_agent_type",
    "get_session_id",
    "get_span_id",
    "get_trace_id",
    "get_user_id",
    "session_id_var",
    "set_agent_type",
    "set_session_id",
    "set_span_id",
    "set_trace_id",
    "set_user_id",
    "span_id_var",
    "trace_id_var",
    "user_id_var",
]
