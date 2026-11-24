"""ORM 模型（可观测性 / 评测 / 运行时支撑表）。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-14] 可靠性/降级
# 职责：ORM 模型（可观测性 / 评测 / 运行时支撑表）
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.common.timeutil import utcnow
from app.infra.db import Base

BigIntPK = Integer().with_variant(mysql.BIGINT(), "mysql")
BigInt = Integer().with_variant(mysql.BIGINT(), "mysql")
MediumText = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class AgentTrace(Base):
    """链路追踪根节点：一次用户提问 = 一条 trace。"""

    __tablename__ = "agent_trace"
    __table_args__ = (Index("idx_trace_session", "session_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_id: Mapped[int] = mapped_column(BigInt, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False, default=0)
    agent_type: Mapped[str | None] = mapped_column(String(24), default=None)
    question: Mapped[str | None] = mapped_column(Text, default=None)
    answer: Mapped[str | None] = mapped_column(MediumText, default=None)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING", nullable=False)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AgentSpan(Base):
    """span：LLM/TOOL/RETRIEVAL/AGENT/GUARDRAIL 五类。"""

    __tablename__ = "agent_span"
    __table_args__ = (Index("idx_span_trace", "trace_id", "seq"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    span_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(64), default=None)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    span_type: Mapped[str] = mapped_column(String(24), nullable=False, default="AGENT")
    seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="OK", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class LlmCall(Base):
    """模型调用账单（含 cached_tokens，成本聚合的唯一数据源）。"""

    __tablename__ = "llm_call"
    __table_args__ = (
        Index("idx_llm_trace", "trace_id"),
        Index("idx_llm_model", "model", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), default=None)
    span_id: Mapped[str | None] = mapped_column(String(64), default=None)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="OK", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("idx_audit_user", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(128), default=None)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class EvalRun(Base):
    __tablename__ = "eval_run"
    __table_args__ = (Index("idx_eval_suite", "suite", "started_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    suite: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING", nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pass_rate: Mapped[float] = mapped_column(Numeric(5, 4, asdecimal=False), default=0, nullable=False)
    pass_k: Mapped[float] = mapped_column(Numeric(5, 4, asdecimal=False), default=0, nullable=False)
    repeat_times: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    avg_cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class EvalCaseResult(Base):
    __tablename__ = "eval_case_result"
    __table_args__ = (Index("idx_case_run", "run_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str | None] = mapped_column(Text, default=None)
    actual: Mapped[str | None] = mapped_column(MediumText, default=None)
    passed: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(4, 3, asdecimal=False), default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)


class IdempotencyRecord(Base):
    """幂等记录：WRITE/IRREVERSIBLE 工具以 idem_key 去重。"""

    __tablename__ = "idempotency_record"

    idem_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class AsyncTask(Base):
    """异步任务兜底表：MQ 不可用时落库，消费者可重放。"""

    __tablename__ = "async_task"
    __table_args__ = (Index("idx_task_status", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    retry: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retry: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AgentCheckpoint(Base):
    """每步状态快照：可重放（/admin/traces/{id}）与审批后恢复执行的依据。"""

    __tablename__ = "agent_checkpoint"
    __table_args__ = (
        UniqueConstraint("trace_id", "step_no", name="uk_ckpt"),
        Index("idx_ckpt_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInt, nullable=False, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class PromptTemplate(Base):
    __tablename__ = "prompt_template"
    __table_args__ = (UniqueConstraint("code", "version", name="uk_prompt_code_ver"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content: Mapped[str] = mapped_column(MediumText, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


__all__ = [
    "AgentCheckpoint",
    "AgentSpan",
    "AgentTrace",
    "AsyncTask",
    "AuditLog",
    "EvalCaseResult",
    "EvalRun",
    "IdempotencyRecord",
    "LlmCall",
    "PromptTemplate",
]
