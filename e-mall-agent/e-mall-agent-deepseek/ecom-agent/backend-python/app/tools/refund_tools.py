"""退款工具：创建退款申请（IRREVERSIBLE，必须人工审批后执行）。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-05] 工具治理
# 职责：退款工具：创建退款申请（IRREVERSIBLE，必须人工审批后执行）
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import Field

from app.common.envelope import CamelModel
from app.common.ids import idempotency_key
from app.infra.db import session_scope
from app.infra.models import OrderInfo, RefundRequest
from app.tools.base import ApprovalRequired, Risk, ToolContext, ToolSpec, now_stamp
from app.tools.order_tools import check_refund_eligibility, refund_amount_of


class CreateRefundArgs(CamelModel):
    orderNo: str = Field(description="订单号")
    reason: str = Field(min_length=2, max_length=200, description="退款原因")
    amount: float | None = Field(default=None, ge=0, description="退款金额，缺省取订单实付金额")


def _new_refund_no() -> str:
    return f"RF{now_stamp()}{random.randint(1000, 9999)}"


def resolve_refund_approval(ctx: ToolContext, kwargs: dict[str, Any]) -> dict[str, Any]:
    """审批单内容：带上订单号、金额、资格结论，方便人工快速判断。"""
    order_no = str(kwargs.get("orderNo", ""))
    reason = str(kwargs.get("reason", ""))
    eligibility = check_refund_eligibility(ctx, order_no)
    amount = kwargs.get("amount")
    if amount is None:
        amount = refund_amount_of(order_no, ctx.user_id) or eligibility.get("payAmount") or 0
    detail = {
        "orderNo": order_no,
        "amount": round(float(amount), 2),
        "reason": reason,
        "eligibility": {
            "eligible": eligibility.get("eligible"),
            "reason": eligibility.get("reason"),
            "deadline": eligibility.get("deadline"),
        },
        "userId": ctx.user_id,
        "sessionId": ctx.session_id,
    }
    return {
        "actionType": "CREATE_REFUND",
        "title": f"退款审批 · {order_no}（¥{round(float(amount), 2)}）",
        "detail": detail,
        "risk": Risk.IRREVERSIBLE.value,
    }


# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：不可逆工具只抛审批信号，无副作用
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
def create_refund_request(ctx: ToolContext, orderNo: str, reason: str, amount: float | None = None) -> dict[str, Any]:
    """IRREVERSIBLE 工具本体：**只有审批通过后**才会被调用。

    直接调用（绕过审批）也会抛 :class:`ApprovalRequired`，防止误用。
    """
    raise ApprovalRequired(
        tool="create_refund_request",
        args={"orderNo": orderNo, "reason": reason, "amount": amount},
        action_type="CREATE_REFUND",
        title=f"退款审批 · {orderNo}",
        detail={"orderNo": orderNo, "reason": reason, "amount": amount},
    )


# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：审批通过后真正落库（幂等）
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
def execute_refund_request(
    ctx: ToolContext,
    order_no: str,
    reason: str,
    amount: float | None = None,
    approval_id: int | None = None,
) -> dict[str, Any]:
    """审批通过后真正落库：创建退款单 + 订单转 REFUNDING（幂等）。"""
    idem = idempotency_key("refund", ctx.user_id, order_no, reason)
    with session_scope() as db:
        order = (
            db.query(OrderInfo)
            .filter(OrderInfo.order_no == order_no.strip(), OrderInfo.user_id == ctx.user_id)
            .one_or_none()
        )
        if order is None:
            return {"ok": False, "error": f"未找到订单 {order_no}"}
        existing = db.query(RefundRequest).filter(RefundRequest.idempotency_key == idem).one_or_none()
        if existing is not None:
            return {
                "ok": True,
                "refundNo": existing.refund_no,
                "status": existing.status,
                "amount": round(float(existing.amount or 0), 2),
                "orderNo": order.order_no,
                "approvalId": existing.approval_id,
                "idempotent": True,
            }
        final_amount = round(float(amount if amount is not None else order.pay_amount or 0), 2)
        refund = RefundRequest(
            refund_no=_new_refund_no(),
            order_id=order.id,
            user_id=ctx.user_id,
            reason=reason[:500],
            amount=final_amount,
            status="APPROVED" if approval_id else "PENDING_APPROVAL",
            idempotency_key=idem,
            approval_id=approval_id,
        )
        db.add(refund)
        order.status = "REFUNDING"
        db.flush()
        result = {
            "ok": True,
            "refundNo": refund.refund_no,
            "status": refund.status,
            "amount": final_amount,
            "orderNo": order.order_no,
            "approvalId": approval_id,
            "idempotent": False,
        }
    return result


def get_refund(ctx: ToolContext, refund_no: str) -> dict[str, Any]:
    """查询退款单（客服场景）。"""
    with session_scope() as db:
        row = (
            db.query(RefundRequest)
            .filter(RefundRequest.refund_no == refund_no, RefundRequest.user_id == ctx.user_id)
            .one_or_none()
        )
        if row is None:
            return {"found": False, "refundNo": refund_no}
        return {
            "found": True,
            "refundNo": row.refund_no,
            "status": row.status,
            "amount": round(float(row.amount or 0), 2),
            "reason": row.reason,
            "approvalId": row.approval_id,
        }


# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：审批后执行适配器（驼峰→蛇形参数映射）
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
def execute_approved_refund(ctx: ToolContext, approval_id: int | None = None, **kwargs: Any) -> dict[str, Any]:
    """审批通过后的执行适配器。

    工具参数经 ``CreateRefundArgs`` 校验后是驼峰键（``orderNo``），而
    :func:`execute_refund_request` 用蛇形形参，这里做一次显式映射，
    避免"审批通过了却因为参数名不匹配而失败"这种隐蔽故障。
    """
    order_no = kwargs.get("orderNo") or kwargs.get("order_no")
    if not order_no:
        return {"ok": False, "error": "缺少订单号"}
    return execute_refund_request(
        ctx,
        order_no=str(order_no),
        reason=str(kwargs.get("reason") or ""),
        amount=kwargs.get("amount"),
        approval_id=approval_id,
    )


CREATE_REFUND_REQUEST = ToolSpec(
    name="create_refund_request",
    description=(
        "为用户创建退款申请。属于不可逆资金操作，必须先经人工审批通过后才会真正执行；"
        "调用后本次对话会挂起并等待审批结果。"
    ),
    func=create_refund_request,
    approved_func=execute_approved_refund,
    risk=Risk.IRREVERSIBLE,
    args_model=CreateRefundArgs,
    timeout_seconds=10,
    action_type="CREATE_REFUND",
    approval_title="退款审批",
    approval_resolver=resolve_refund_approval,
    audit_target_fields=("orderNo",),
    summarize=lambda data: f"退款单 {data.get('refundNo')} 已创建",
)


def refund_detail_json(detail: dict[str, Any]) -> str:
    """审批详情序列化（前端展示用）。"""
    return json.dumps(detail, ensure_ascii=False, default=str)


__all__ = [
    "CREATE_REFUND_REQUEST",
    "CreateRefundArgs",
    "create_refund_request",
    "execute_approved_refund",
    "execute_refund_request",
    "get_refund",
    "refund_detail_json",
    "resolve_refund_approval",
]
