"""链路追踪：TraceRecorder 负责写 ``agent_trace`` / ``agent_span`` / ``agent_checkpoint``。

约定：
* 一次用户提问 = 一个 trace；一次模型调用 / 一次工具调用 / 一次检索 = 一个 span；
* span 写入失败绝不影响主流程（只告警），保证可观测性不与业务耦合；
* span 的 ``seq`` 严格自增，供 ``/admin/traces/{traceId}`` 顺序回放。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-16] 可观测与调试
# 职责：链路追踪：TraceRecorder 负责写 ``agent_trace`` / ``agent_span`` / ``
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.common.ids import new_span_id
from app.common.timeutil import utcnow
from app.common.tracecontext import set_span_id
from app.infra import models_obs
from app.infra.db import session_scope

logger = logging.getLogger(__name__)

SPAN_LLM = "LLM"
SPAN_TOOL = "TOOL"
SPAN_RETRIEVAL = "RETRIEVAL"
SPAN_AGENT = "AGENT"
SPAN_GUARDRAIL = "GUARDRAIL"


class Span:
    """单个 span 的运行时句柄。"""

    def __init__(self, name: str, span_type: str, span_id: str, parent_span_id: str | None) -> None:
        self.name = name
        self.span_type = span_type
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.started_at = time.perf_counter()
        self.status = "OK"
        self.error: str | None = None
        self.output: dict[str, Any] = {}

    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.started_at) * 1000)


# ──────── [CAP-16] 可观测与调试 ────────
#   本处：trace/span 落库
#   域约束：span 必须 try/finally 收口；不打印完整 prompt，只记 hash 与长度
class TraceRecorder:
    """trace 生命周期管理（可在任意线程调用，内部每次独立 Session）。"""

    def __init__(
        self,
        trace_id: str,
        session_id: int,
        user_id: int,
        agent_type: str | None = None,
        question: str | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.session_id = session_id
        self.user_id = user_id
        self.agent_type = agent_type
        self.question = question
        self.step_count = 0
        self.total_cost_cents = 0
        self.started_at = time.perf_counter()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._root_span_id: str | None = None

    # --- 生命周期 -----------------------------------------------------------
    def start(self) -> None:
        """落 agent_trace（RUNNING）。"""
        try:
            with session_scope() as db:
                db.add(
                    models_obs.AgentTrace(
                        trace_id=self.trace_id,
                        session_id=self.session_id,
                        user_id=self.user_id,
                        agent_type=self.agent_type,
                        question=self.question,
                        status="RUNNING",
                        step_count=0,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 agent_trace 失败: %s", exc)

    def finish(
        self,
        status: str,
        answer: str | None = None,
        step_count: int | None = None,
        cost_cents: int | None = None,
        agent_type: str | None = None,
    ) -> None:
        """结束 trace：更新状态、答案、耗时、成本、步数。"""
        total_latency = int((time.perf_counter() - self.started_at) * 1000)
        try:
            with session_scope() as db:
                row = db.query(models_obs.AgentTrace).filter(
                    models_obs.AgentTrace.trace_id == self.trace_id
                ).one_or_none()
                if row is None:
                    db.add(
                        models_obs.AgentTrace(
                            trace_id=self.trace_id,
                            session_id=self.session_id,
                            user_id=self.user_id,
                            agent_type=agent_type or self.agent_type,
                            question=self.question,
                            answer=answer,
                            status=status,
                            total_latency_ms=total_latency,
                            total_cost_cents=cost_cents or 0,
                            step_count=step_count or 0,
                        )
                    )
                else:
                    row.status = status
                    if answer is not None:
                        row.answer = answer
                    row.total_latency_ms = total_latency
                    row.total_cost_cents = cost_cents if cost_cents is not None else row.total_cost_cents
                    row.step_count = step_count if step_count is not None else row.step_count
                    if agent_type:
                        row.agent_type = agent_type
        except Exception as exc:  # noqa: BLE001
            logger.warning("更新 agent_trace 失败: %s", exc)

    # --- span ---------------------------------------------------------------
    def next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    @contextmanager
    def span(
        self,
        name: str,
        span_type: str = SPAN_AGENT,
        inputs: dict[str, Any] | None = None,
        parent_span_id: str | None = None,
    ) -> Iterator[Span]:
        """同步上下文管理器：自动记录耗时、状态与异常。"""
        span = Span(name=name, span_type=span_type, span_id=new_span_id(), parent_span_id=parent_span_id)
        set_span_id(span.span_id)
        seq = self.next_seq()
        try:
            yield span
        except Exception as exc:  # noqa: BLE001 - 记录后继续抛出
            span.status = "ERROR"
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._write_span(span, seq, inputs or {})

    def record_span(
        self,
        name: str,
        span_type: str,
        inputs: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        latency_ms: int = 0,
        status: str = "OK",
        error: str | None = None,
        parent_span_id: str | None = None,
    ) -> Span:
        """直接写一个已完成的 span（性能敏感路径用，无需 with 语法）。"""
        span = Span(
            name=name,
            span_type=span_type,
            span_id=new_span_id(),
            parent_span_id=parent_span_id,
        )
        span.status = status
        span.error = error
        span.output = output or {}
        span.started_at = time.perf_counter() - latency_ms / 1000.0
        self._write_span(span, self.next_seq(), inputs or {}, latency_ms=latency_ms)
        return span

    def _write_span(
        self, span: Span, seq: int, inputs: dict[str, Any], latency_ms: int | None = None
    ) -> None:
        latency = span.latency_ms if latency_ms is None else latency_ms
        try:
            with session_scope() as db:
                db.add(
                    models_obs.AgentSpan(
                        trace_id=self.trace_id,
                        span_id=span.span_id,
                        parent_span_id=span.parent_span_id or self._root_span_id,
                        name=span.name[:128],
                        span_type=span.span_type,
                        seq=seq,
                        input=_jsonable(inputs),
                        output=_jsonable(span.output),
                        latency_ms=latency,
                        status=span.status,
                        error=(span.error or "")[:4000] or None,
                        started_at=utcnow(),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 agent_span 失败 name=%s err=%s", span.name, exc)

    # --- checkpoint ---------------------------------------------------------
    # ──────── [CAP-16] 可观测与调试 ────────
    #   本处：每步状态快照（可重放）
    #   域约束：span 必须 try/finally 收口；不打印完整 prompt，只记 hash 与长度
    def checkpoint(self, step_no: int, state: dict[str, Any]) -> None:
        """每步状态快照（可重放 / 审批后恢复）。"""
        try:
            with session_scope() as db:
                exists = (
                    db.query(models_obs.AgentCheckpoint.id)
                    .filter(
                        models_obs.AgentCheckpoint.trace_id == self.trace_id,
                        models_obs.AgentCheckpoint.step_no == step_no,
                    )
                    .one_or_none()
                )
                if exists:
                    return
                db.add(
                    models_obs.AgentCheckpoint(
                        session_id=self.session_id,
                        trace_id=self.trace_id,
                        step_no=step_no,
                        state=_jsonable(state),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 agent_checkpoint 失败 step=%s err=%s", step_no, exc)

    def load_checkpoints(self) -> list[dict[str, Any]]:
        """读取全部 checkpoint（重放/恢复用）。"""
        try:
            with session_scope() as db:
                rows = (
                    db.query(models_obs.AgentCheckpoint)
                    .filter(models_obs.AgentCheckpoint.trace_id == self.trace_id)
                    .order_by(models_obs.AgentCheckpoint.step_no.asc())
                    .all()
                )
                return [{"stepNo": row.step_no, "state": row.state, "createdAt": str(row.created_at)} for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 agent_checkpoint 失败: %s", exc)
            return []


def _jsonable(value: Any) -> Any:
    """把 span 的输入输出裁剪为可 JSON 序列化的结构。"""
    import json

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return {"repr": str(value)[:2000]}


__all__ = [
    "SPAN_AGENT",
    "SPAN_GUARDRAIL",
    "SPAN_LLM",
    "SPAN_RETRIEVAL",
    "SPAN_TOOL",
    "Span",
    "TraceRecorder",
]
