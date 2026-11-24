"""Human-in-the-loop：审批任务的创建、查询、决策、执行与超时。

状态机（与 docs/04 §4.5 一致）::

    PENDING ──approve──> APPROVED ──> 执行动作 ──> 回写业务结果
        │
        ├──reject──> REJECTED
        └──timeout─> EXPIRED

关键约束：
1. **只有 PENDING 且未过期的任务可被决策**，重复决策返回 40900；
2. **决策人必须是任务归属人**，否则按"不存在"处理（防枚举）；
3. 审批通过后动作通过 MQ 异步执行；MQ 不可用时**就地执行**，保证本地可跑通；
4. 执行结果以系统消息回写会话，用户在前端能看到最终状态。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-10] 人机协作 HITL
# 职责：Human-in-the-loop：审批任务的创建、查询、决策、执行与超时
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from datetime import timedelta
from typing import Any

from app.common.errors import conflict, not_found
from app.common.ids import new_trace_id
from app.common.timeutil import utcnow
from app.config import settings
from app.infra.db import session_scope
from app.infra.models import ApprovalTask
from app.obs.trace import SPAN_TOOL, TraceRecorder

logger = logging.getLogger(__name__)

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_EXPIRED = "EXPIRED"

DECISION_APPROVE = "APPROVE"
DECISION_REJECT = "REJECT"


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------
def create(
    *,
    session_id: int,
    user_id: int,
    action_type: str,
    title: str,
    detail: dict[str, Any] | None = None,
    risk: str = "IRREVERSIBLE",
    trace_id: str | None = None,
    message_id: int | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """创建审批任务，返回 ApprovalVO（含 expiresAt）。"""
    ttl = ttl_seconds or settings.approval_timeout_seconds
    expires_at = utcnow() + timedelta(seconds=ttl)
    payload = dict(detail or {})
    if trace_id:
        payload.setdefault("traceId", trace_id)

    with session_scope() as db:
        row = ApprovalTask(
            session_id=session_id,
            message_id=message_id,
            user_id=user_id,
            action_type=action_type[:48],
            title=title[:255],
            detail=payload,
            risk=risk,
            status=STATUS_PENDING,
            expires_at=expires_at,
        )
        db.add(row)
        db.flush()
        return to_vo(row)


def to_vo(row: ApprovalTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "sessionId": row.session_id,
        "actionType": row.action_type,
        "title": row.title,
        "detail": row.detail or {},
        "risk": row.risk,
        "status": row.status,
        "createdAt": _iso(row.created_at),
        "expiresAt": _iso(row.expires_at),
        "decidedAt": _iso(row.decided_at),
        "decisionComment": row.decision_comment,
    }


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def list_tasks(user_id: int, status: str = STATUS_PENDING, limit: int = 20) -> list[dict[str, Any]]:
    with session_scope() as db:
        query = db.query(ApprovalTask).filter(ApprovalTask.user_id == user_id)
        if status:
            query = query.filter(ApprovalTask.status == status.upper())
        rows = query.order_by(ApprovalTask.id.desc()).limit(limit).all()
        return [to_vo(row) for row in rows]


def get_task(approval_id: int) -> dict[str, Any] | None:
    with session_scope() as db:
        row = db.get(ApprovalTask, approval_id)
        return to_vo(row) if row else None


def pending_count(user_id: int | None = None) -> int:
    with session_scope() as db:
        query = db.query(ApprovalTask).filter(ApprovalTask.status == STATUS_PENDING)
        if user_id is not None:
            query = query.filter(ApprovalTask.user_id == user_id)
        return int(query.count())


# ---------------------------------------------------------------------------
# 决策
# ---------------------------------------------------------------------------
# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：审批决策入口（授权 + 状态机）
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
async def decide(
    approval_id: int,
    user_id: int,
    decision: str,
    comment: str | None = None,
    *,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    """处理审批决策；通过则触发动作执行。

    权限规则：**申请人本人** 或 **ADMIN / OPS 角色** 可以决策。
    客服坐席代客审批是真实业务需求，不能只允许本人。

    返回 ``{"id", "status", "result"}``。
    """
    action = (decision or "").strip().upper()
    if action not in (DECISION_APPROVE, DECISION_REJECT):
        raise conflict("决策只能是 APPROVE 或 REJECT")

    task = _claim_for_decision(approval_id, user_id, action, comment, roles or [])

    if action == DECISION_REJECT:
        _mark_business_rejected(task)
        _notify(task, "已拒绝该操作，如有疑问可转人工客服进一步说明。")
        return {"id": approval_id, "status": STATUS_REJECTED, "result": {"rejected": True}}

    result = await _execute_approved(task)
    return {"id": approval_id, "status": STATUS_APPROVED, "result": result}


# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：抢占式状态更新（防并发双批）
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
def _claim_for_decision(
    approval_id: int,
    user_id: int,
    action: str,
    comment: str | None,
    roles: list[str],
) -> dict[str, Any]:
    """抢占式更新状态，避免并发重复决策。"""
    privileged = {str(r).upper() for r in roles} & {"ADMIN", "OPS"}
    with session_scope() as db:
        row = db.get(ApprovalTask, approval_id)
        # 无权访问时按"不存在"处理，避免枚举他人审批单
        if row is None or (row.user_id != user_id and not privileged):
            raise not_found("审批任务不存在")
        if row.status != STATUS_PENDING:
            raise conflict(f"该审批已处理（当前状态 {row.status}）")
        if row.expires_at is not None and row.expires_at < utcnow():
            row.status = STATUS_EXPIRED
            raise conflict("审批已超时，请重新发起")

        row.status = STATUS_APPROVED if action == DECISION_APPROVE else STATUS_REJECTED
        row.decision_comment = (comment or "")[:512] or None
        row.decided_by = user_id
        row.decided_at = utcnow()
        return to_vo(row)


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：MQ 异步执行，投递失败就地执行
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
async def _execute_approved(task: dict[str, Any]) -> dict[str, Any]:
    """审批通过后的执行：优先 MQ 异步，投递失败就地执行。"""
    detail = task.get("detail") or {}
    tool_name = str(detail.get("tool") or "")
    args = detail.get("args") or {}

    payload = {
        "approvalId": task["id"],
        "sessionId": task["sessionId"],
        "userId": detail.get("userId"),
        "tool": tool_name,
        "args": args,
    }

    delivered = False
    try:
        from app.infra.rabbit import message_bus

        delivered = await message_bus.publish_async("refund.execute", payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("审批执行任务投递失败，转就地执行: %s", exc)

    if not delivered:
        return await execute_action(payload)

    _notify(task, "审批已通过，正在为你处理，请稍候。")
    return {"queued": True}


# ──────── [CAP-08] 工作流 / 状态机 ────────
#   本处：审批动作执行（幂等 + 审计）
#   域约束：状态迁移用期望旧状态做 CAS（UPDATE ... WHERE status=旧值），禁止先查后写
async def execute_action(payload: dict[str, Any]) -> dict[str, Any]:
    """真正执行被审批的动作（幂等由业务工具保证）。"""
    tool_name = str(payload.get("tool") or "")
    args = payload.get("args") or {}
    if not tool_name:
        return {"ok": False, "error": "缺少待执行工具"}

    from app.tools.base import ToolContext
    from app.tools.registry import get_spec

    try:
        spec = get_spec(tool_name)
    except KeyError:
        return {"ok": False, "error": f"未知工具 {tool_name}"}

    user_id = int(payload.get("userId") or 0)
    session_id = int(payload.get("sessionId") or 0)
    trace_id = new_trace_id()
    recorder = TraceRecorder(trace_id=trace_id, session_id=session_id, user_id=user_id)
    ctx = ToolContext(
        user_id=user_id,
        session_id=session_id,
        trace_id=trace_id,
        agent_type="SERVICE",
        recorder=recorder,
    )

    try:
        kwargs = spec.validate(args)
        # IRREVERSIBLE 工具的 func 只负责抛审批中断，真正的副作用在 approved_func 里
        target = spec.approved_func or spec.func
        if spec.approved_func is not None:
            kwargs = {**kwargs, "approval_id": int(payload.get("approvalId") or 0) or None}
        if inspect.iscoroutinefunction(target):
            data = await target(ctx, **kwargs)
        else:
            data = await asyncio.to_thread(target, ctx, **kwargs)
        result = data if isinstance(data, dict) else {"ok": False, "error": "工具返回格式异常"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("审批动作执行失败 tool=%s", tool_name)
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    recorder.record_span(
        name=f"approval.execute.{tool_name}",
        span_type=SPAN_TOOL,
        inputs={"args": args, "approvalId": payload.get("approvalId")},
        output=result,
        status="OK" if result.get("ok", True) else "ERROR",
        error=result.get("error"),
    )

    task = get_task(int(payload.get("approvalId") or 0))
    if task:
        if result.get("ok", True):
            _notify(task, _success_message(tool_name, result))
        else:
            _notify(task, f"处理失败：{result.get('error') or '未知原因'}。建议转人工客服处理。")
    return result


def _success_message(tool_name: str, result: dict[str, Any]) -> str:
    if tool_name == "create_refund_request":
        refund_no = result.get("refundNo") or result.get("refund_no") or "-"
        amount = result.get("amount")
        amount_text = f"{amount} 元" if amount is not None else ""
        return f"退款申请已提交成功（单号 {refund_no}，金额 {amount_text}），预计 1-3 个工作日原路退回。"
    return "操作已完成。"


def _mark_business_rejected(task: dict[str, Any]) -> None:
    """审批被拒时同步更新业务状态（如退款单置为 REJECTED）。"""
    detail = task.get("detail") or {}
    refund_id = detail.get("refundId")
    if not refund_id:
        return
    try:
        from app.infra.models import RefundRequest

        with session_scope() as db:
            row = db.get(RefundRequest, int(refund_id))
            if row is not None and row.status in ("PENDING_APPROVAL", "PROCESSING"):
                row.status = "REJECTED"
    except Exception as exc:  # noqa: BLE001
        logger.warning("回写退款拒绝状态失败: %s", exc)


def _notify(task: dict[str, Any], content: str) -> None:
    """把执行结果以系统消息回写会话。"""
    try:
        from app.memory import session as session_memory

        session_memory.append_message(
            int(task["sessionId"]),
            "assistant",
            content,
            agent_type="SERVICE",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("审批结果回写会话失败: %s", exc)


# ---------------------------------------------------------------------------
# 超时
# ---------------------------------------------------------------------------
def expire_overdue() -> int:
    """把超时未决策的任务置为 EXPIRED，返回条数。"""
    now = utcnow()
    count = 0
    try:
        with session_scope() as db:
            rows = (
                db.query(ApprovalTask)
                .filter(ApprovalTask.status == STATUS_PENDING, ApprovalTask.expires_at < now)
                .all()
            )
            for row in rows:
                row.status = STATUS_EXPIRED
                row.decided_at = now
                count += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("审批超时扫描失败: %s", exc)
    return count


def approval_from_exception(exc: Any, *, session_id: int, user_id: int, trace_id: str | None) -> dict[str, Any]:
    """把 ``ApprovalRequired`` 异常转成审批任务。

    ``detail`` 里保留工具名与参数，审批通过后据此执行（不重跑整个 Agent）。
    """
    detail = dict(getattr(exc, "detail", None) or {})
    detail.update(
        {
            "tool": getattr(exc, "tool", ""),
            "args": dict(getattr(exc, "tool_args", None) or {}),
            "userId": user_id,
        }
    )
    return create(
        session_id=session_id,
        user_id=user_id,
        action_type=getattr(exc, "action_type", "UNKNOWN"),
        title=getattr(exc, "title", "需要审批"),
        detail=detail,
        risk=str(getattr(getattr(exc, "risk", None), "value", "IRREVERSIBLE")),
        trace_id=trace_id,
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return str(value)


def dumps(value: Any) -> str:
    """调试用：稳定 JSON 序列化。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


__all__ = [
    "DECISION_APPROVE",
    "DECISION_REJECT",
    "STATUS_APPROVED",
    "STATUS_EXPIRED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "approval_from_exception",
    "create",
    "decide",
    "execute_action",
    "expire_overdue",
    "get_task",
    "list_tasks",
    "pending_count",
    "to_vo",
]
