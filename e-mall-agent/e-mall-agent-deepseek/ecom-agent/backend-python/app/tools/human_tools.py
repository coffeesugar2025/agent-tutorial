"""人工协同工具：转人工 / 建工单。

工单复用 ``async_task`` 表（``task_type=human.handoff``），不污染 ``approval_task``
（后者专用于 IRREVERSIBLE 工具的审批），同时写审计日志留下操作轨迹。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.common.envelope import CamelModel
from app.common.timeutil import iso_now
from app.infra import models_obs
from app.infra.db import session_scope
from app.infra.rabbit import persist_task
from app.security.injection import sanitize_for_audit
from app.tools.base import Risk, ToolContext, ToolSpec


class EscalateArgs(CamelModel):
    reason: str = Field(min_length=2, max_length=200, description="转人工原因")
    summary: str | None = Field(default=None, max_length=1000, description="问题摘要，便于客服接手")


def escalate_to_human(ctx: ToolContext, reason: str, summary: str | None = None) -> dict[str, Any]:
    """创建人工工单并记录审计。"""
    payload = {
        "userId": ctx.user_id,
        "sessionId": ctx.session_id,
        "traceId": ctx.trace_id,
        "agentType": ctx.agent_type,
        "reason": sanitize_for_audit(reason, 200),
        "summary": sanitize_for_audit(summary or reason, 1000),
        "createdAt": iso_now(),
    }
    ticket_id = persist_task("human.handoff", payload, status="QUEUED")
    try:
        with session_scope() as db:
            db.add(
                models_obs.AuditLog(
                    user_id=ctx.user_id,
                    action="tool.escalate_to_human",
                    target=f"ticket:{ticket_id}" if ticket_id else "ticket:0",
                    detail={"reason": payload["reason"], "traceId": ctx.trace_id},
                )
            )
    except Exception:  # noqa: BLE001 - 审计失败不影响转人工结果
        pass
    return {
        "ok": True,
        "ticketId": ticket_id,
        "status": "QUEUED",
        "message": "已为你转接人工客服，工单创建成功，客服会尽快处理",
        "reason": reason,
    }


ESCALATE_TO_HUMAN = ToolSpec(
    name="escalate_to_human",
    description="当问题超出自动处理范围（复杂投诉、异常订单、模型无法确认）时转接人工客服并建工单。",
    func=escalate_to_human,
    risk=Risk.WRITE,
    args_model=EscalateArgs,
    timeout_seconds=10,
    max_retries=0,
    summarize=lambda data: f"已创建人工工单 #{data.get('ticketId')}",
    audit_target_fields=("reason",),
)

__all__ = ["ESCALATE_TO_HUMAN", "escalate_to_human"]
