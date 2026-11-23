"""会话记忆：会话 CRUD、消息落库、历史装载、滚动摘要触发。

设计要点：
* 所有函数自带短事务（``session_scope``），调用方无需关心连接生命周期；
* 历史装载做**预算裁剪**：超长时保留最近 N 轮 + 会话摘要（摘要优先于早期原文）；
* 消息条数超过阈值时投递 ``session.summarize`` 到 MQ，异步生成摘要，不阻塞对话。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.common.errors import not_found
from app.common.timeutil import utcnow
from app.config import settings
from app.infra.db import session_scope
from app.infra.models import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
def create_session(user_id: int, title: str | None = None, agent_type: str = "SUPERVISOR") -> dict[str, Any]:
    """新建会话，返回会话 VO。"""
    with session_scope() as db:
        row = ChatSession(
            user_id=user_id,
            title=(title or "新会话")[:255],
            agent_type=agent_type,
            status="ACTIVE",
            last_message_at=utcnow(),
        )
        db.add(row)
        db.flush()
        return to_vo(row)


def list_sessions(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """按最近活跃倒序列出会话。"""
    with session_scope() as db:
        rows = (
            db.query(ChatSession)
            .filter(ChatSession.user_id == user_id, ChatSession.status != "DELETED")
            .order_by(ChatSession.last_message_at.desc(), ChatSession.id.desc())
            .limit(limit)
            .all()
        )
        return [to_vo(row) for row in rows]


def get_session(session_id: int, user_id: int) -> dict[str, Any]:
    with session_scope() as db:
        return to_vo(_owned(db, session_id, user_id))


def delete_session(session_id: int, user_id: int) -> None:
    with session_scope() as db:
        row = _owned(db, session_id, user_id)
        row.status = "DELETED"


def rename_session(session_id: int, user_id: int, title: str) -> dict[str, Any]:
    with session_scope() as db:
        row = _owned(db, session_id, user_id)
        row.title = title[:255]
        return to_vo(row)


def _owned(db: Session, session_id: int, user_id: int) -> ChatSession:
    row = db.get(ChatSession, session_id)
    if row is None or row.status == "DELETED":
        raise not_found("会话不存在")
    if row.user_id != user_id:
        # 不区分"不存在"与"无权"，避免枚举他人会话
        raise not_found("会话不存在")
    return row


def to_vo(row: ChatSession) -> dict[str, Any]:
    """会话对外结构（与 docs/03 SessionVO 一致）。"""
    return {
        "id": row.id,
        "title": row.title,
        "agentType": row.agent_type,
        "status": row.status,
        "lastMessageAt": _iso(row.last_message_at),
        "createdAt": _iso(row.created_at),
    }


# ---------------------------------------------------------------------------
# 消息
# ---------------------------------------------------------------------------
def append_message(
    session_id: int,
    role: str,
    content: str | None = None,
    *,
    agent_type: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    token_in: int = 0,
    token_out: int = 0,
    cost_cents: int = 0,
    trace_id: str | None = None,
) -> int:
    """写一条消息并刷新会话活跃时间，返回消息 id。"""
    with session_scope() as db:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            agent_type=agent_type,
            tool_calls=tool_calls or None,
            citations=citations or None,
            token_in=token_in,
            token_out=token_out,
            cost_cents=cost_cents,
            trace_id=trace_id,
        )
        db.add(msg)
        session = db.get(ChatSession, session_id)
        if session is not None:
            session.last_message_at = utcnow()
            if agent_type and agent_type != "SUPERVISOR":
                session.agent_type = agent_type
            # 首条用户消息自动命名会话
            if role == ROLE_USER and session.title in ("新会话", "", None):
                session.title = (content or "新会话").strip().replace("\n", " ")[:30]
        db.flush()
        return int(msg.id)


def list_messages(session_id: int, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """按时间正序返回最近 ``limit`` 条消息。"""
    with session_scope() as db:
        _owned(db, session_id, user_id)
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id, ChatMessage.role != ROLE_TOOL)
            .order_by(ChatMessage.id.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [to_message_vo(row) for row in reversed(rows)]


def to_message_vo(row: ChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "role": row.role,
        "content": row.content,
        "agentType": row.agent_type,
        "toolCalls": row.tool_calls or [],
        "citations": row.citations or [],
        "tokenIn": row.token_in,
        "tokenOut": row.token_out,
        "costCents": row.cost_cents,
        "createdAt": _iso(row.created_at),
    }


def count_messages(session_id: int) -> int:
    with session_scope() as db:
        return int(
            db.query(func.count(ChatMessage.id))
            .filter(ChatMessage.session_id == session_id, ChatMessage.role != ROLE_TOOL)
            .scalar()
            or 0
        )


# ---------------------------------------------------------------------------
# 历史装载（供 LLM 使用）
# ---------------------------------------------------------------------------
def history_dicts(session_id: int, limit: int | None = None) -> list[dict[str, str]]:
    """轻量历史（路由判断指代用）。"""
    limit = limit or settings.session_history_limit
    with session_scope() as db:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id, ChatMessage.role.in_((ROLE_USER, ROLE_ASSISTANT)))
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {"role": row.role, "content": row.content or ""}
            for row in reversed(rows)
        ]


def load_for_llm(session_id: int) -> tuple[list[Any], str | None]:
    """返回 ``(LangChain 消息列表, 会话摘要)``，已按条数裁剪。

    摘要优先于早期原文：有摘要时只保留最近 ``session_history_limit`` 条原文。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    limit = settings.session_history_limit
    with session_scope() as db:
        session = db.get(ChatSession, session_id)
        summary = session.summary if session is not None else None
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id, ChatMessage.role.in_((ROLE_USER, ROLE_ASSISTANT)))
            .order_by(ChatMessage.id.desc())
            .limit(limit)
            .all()
        )
        messages: list[Any] = []
        for row in reversed(rows):
            if not row.content:
                continue
            if row.role == ROLE_USER:
                messages.append(HumanMessage(content=row.content))
            else:
                messages.append(AIMessage(content=row.content))
        return messages, summary


# ---------------------------------------------------------------------------
# 摘要
# ---------------------------------------------------------------------------
def maybe_trigger_summary(session_id: int, message_count: int) -> bool:
    """消息达到阈值时异步触发摘要（不阻塞主流程）。

    返回是否真的投递了任务。MQ 不可用时 ``message_bus`` 会落 ``async_task`` 兜底。
    """
    if message_count < settings.summary_trigger_messages:
        return False
    if message_count % settings.summary_trigger_messages != 0:
        # 只在阈值整数倍触发，避免每轮都发
        return False
    try:
        import asyncio

        from app.infra.rabbit import message_bus

        payload = {"sessionId": session_id, "upToMessageId": 0}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(message_bus.publish_async("session.summarize", payload))
        else:  # pragma: no cover - 同步上下文（脚本/测试）
            message_bus.publish("session.summarize", payload)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("触发会话摘要失败 session=%s err=%s", session_id, exc)
        return False


def update_summary(session_id: int, summary: str) -> None:
    with session_scope() as db:
        row = db.get(ChatSession, session_id)
        if row is not None:
            row.summary = summary[:8000]


def build_summary_text(messages: list[dict[str, str]], previous: str | None = None) -> str:
    """规则式摘要兜底（LLM 不可用时使用）：抽取用户诉求与已给结论。"""
    user_lines = [m["content"] for m in messages if m.get("role") == ROLE_USER and m.get("content")]
    head = previous.strip() + "\n" if previous else ""
    if not user_lines:
        return head + "（无有效对话）"
    latest = "；".join(line.replace("\n", " ")[:60] for line in user_lines[-6:])
    return (head + "用户近期诉求：" + latest)[:4000]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return str(value)


__all__ = [
    "append_message",
    "build_summary_text",
    "count_messages",
    "create_session",
    "delete_session",
    "get_session",
    "history_dicts",
    "list_messages",
    "list_sessions",
    "load_for_llm",
    "maybe_trigger_summary",
    "rename_session",
    "to_message_vo",
    "to_vo",
    "update_summary",
]
