"""订单类工具：订单查询、列表、物流、退款资格校验。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import Field

from app.common.envelope import CamelModel
from app.common.timeutil import to_iso, utcnow
from app.config import settings
from app.infra.db import session_scope
from app.infra.models import Logistics, OrderInfo, OrderItem
from app.security.pii import mask_phone
from app.tools.base import Risk, ToolContext, ToolSpec

REFUND_WINDOW_DAYS = 7
_ELIGIBLE_STATUS = {"DELIVERED", "FINISHED"}
_PRE_SHIP_STATUS = {"CREATED", "PAID"}


class OrderNoArgs(CamelModel):
    orderNo: str = Field(description="订单号，如 SO202611230001")


class ListOrdersArgs(CamelModel):
    status: str | None = Field(default=None, description="订单状态过滤，如 SHIPPED")
    limit: int = Field(default=5, ge=1, le=20, description="返回条数")


def order_to_dict(db: Any, order: OrderInfo) -> dict[str, Any]:
    """ORM → OrderVO（收货手机号脱敏，符合契约示例）。"""
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    return {
        "id": order.id,
        "orderNo": order.order_no,
        "status": order.status,
        "totalAmount": round(float(order.total_amount or 0), 2),
        "payAmount": round(float(order.pay_amount or 0), 2),
        "receiverName": order.receiver_name,
        "receiverPhone": mask_phone(order.receiver_phone or ""),
        "receiverAddress": order.receiver_address,
        "createdAt": to_iso(order.created_at),
        "paidAt": to_iso(order.paid_at),
        "shippedAt": to_iso(order.shipped_at),
        "finishedAt": to_iso(order.finished_at),
        "items": [
            {
                "sku": item.sku,
                "title": item.title,
                "price": round(float(item.price or 0), 2),
                "quantity": item.quantity,
            }
            for item in items
        ],
    }


def _find_order(db: Any, order_no: str, user_id: int) -> OrderInfo | None:
    return (
        db.query(OrderInfo)
        .filter(OrderInfo.order_no == order_no.strip(), OrderInfo.user_id == user_id)
        .one_or_none()
    )


def get_order(ctx: ToolContext, orderNo: str) -> dict[str, Any]:
    """按订单号查询当前用户的订单详情。"""
    with session_scope() as db:
        order = _find_order(db, orderNo, ctx.user_id)
        if order is None:
            return {"found": False, "orderNo": orderNo, "message": f"未找到订单 {orderNo}"}
        data = order_to_dict(db, order)
        return {"found": True, "order": data, "summary": f"订单 {data['orderNo']} 状态 {data['status']}"}


def list_orders(ctx: ToolContext, status: str | None = None, limit: int = 5) -> dict[str, Any]:
    """列出当前用户最近订单。"""
    with session_scope() as db:
        stmt = db.query(OrderInfo).filter(OrderInfo.user_id == ctx.user_id)
        if status:
            stmt = stmt.filter(OrderInfo.status == status.upper())
        orders = stmt.order_by(OrderInfo.created_at.desc()).limit(limit).all()
        items = []
        for order in orders:
            items.append(
                {
                    "orderNo": order.order_no,
                    "status": order.status,
                    "payAmount": round(float(order.pay_amount or 0), 2),
                    "createdAt": to_iso(order.created_at),
                    "items": [
                        {"sku": item.sku, "title": item.title, "quantity": item.quantity}
                        for item in db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
                    ],
                }
            )
        return {"items": items, "total": len(items), "status": status}


def get_logistics(ctx: ToolContext, orderNo: str) -> dict[str, Any]:
    """查询订单物流轨迹。"""
    with session_scope() as db:
        order = _find_order(db, orderNo, ctx.user_id)
        if order is None:
            return {"found": False, "orderNo": orderNo, "message": f"未找到订单 {orderNo}"}
        row = db.query(Logistics).filter(Logistics.order_id == order.id).one_or_none()
        if row is None:
            return {
                "found": False,
                "orderNo": orderNo,
                "status": "PENDING",
                "message": "该订单还没有物流记录，商家可能尚未发货",
            }
        return {
            "found": True,
            "orderNo": orderNo,
            "company": row.company,
            "trackingNo": row.tracking_no,
            "status": row.status,
            "latestEvent": row.latest_event,
            "events": list(row.events or []),
            "updatedAt": to_iso(row.updated_at),
        }


def check_refund_eligibility(ctx: ToolContext, orderNo: str) -> dict[str, Any]:
    """退款资格校验：状态 + 时间窗 + 金额阈值。"""
    with session_scope() as db:
        order = _find_order(db, orderNo, ctx.user_id)
        if order is None:
            return {
                "eligible": False,
                "orderNo": orderNo,
                "reason": f"未找到订单 {orderNo}，请确认订单号是否正确",
            }
        pay_amount = round(float(order.pay_amount or 0), 2)
        amount_cents = int(round(pay_amount * 100))
        requires_approval = amount_cents > settings.approval_amount_threshold_cents
        base_time = order.finished_at or order.shipped_at or order.paid_at or order.created_at
        deadline = (base_time + timedelta(days=REFUND_WINDOW_DAYS)) if base_time else None
        result: dict[str, Any] = {
            "orderNo": order.order_no,
            "status": order.status,
            "payAmount": pay_amount,
            "amountCents": amount_cents,
            "requiresApproval": requires_approval,
            "refundWindowDays": REFUND_WINDOW_DAYS,
            "deadline": to_iso(deadline),
        }
        if order.status in {"REFUNDING", "REFUNDED"}:
            result.update(eligible=False, reason="该订单已在退款流程中，请勿重复申请")
        elif order.status == "CANCELLED":
            result.update(eligible=False, reason="订单已取消，无需申请退款")
        elif order.status in _PRE_SHIP_STATUS:
            result.update(eligible=True, reason="订单尚未发货，可直接申请仅退款")
        elif order.status in _ELIGIBLE_STATUS:
            if deadline and utcnow() <= deadline:
                result.update(eligible=True, reason=f"订单在 {REFUND_WINDOW_DAYS} 天无理由退货期内")
            else:
                result.update(eligible=False, reason="已超过 7 天无理由退货期，如有质量问题请转人工处理")
        elif order.status == "SHIPPED":
            result.update(eligible=False, reason="商品运输中，建议签收后再申请退货退款")
        else:
            result.update(eligible=False, reason="当前订单状态不支持自助退款，请转人工客服")
        if requires_approval and result.get("eligible"):
            result["reason"] = f"{result['reason']}；金额较大（¥{pay_amount}）需人工审批"
        return result


def refund_amount_of(order_no: str, user_id: int) -> float:
    """审批流用：取订单应付金额（找不到时返回 0）。"""
    with session_scope() as db:
        order = _find_order(db, order_no, user_id)
        return round(float(order.pay_amount or 0), 2) if order else 0.0


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
GET_ORDER = ToolSpec(
    name="get_order",
    description="根据订单号查询当前用户的订单详情（状态、金额、商品明细）。",
    func=get_order,
    risk=Risk.READ,
    args_model=OrderNoArgs,
    timeout_seconds=8,
    max_retries=1,
    summarize=lambda data: data.get("summary") or data.get("message", ""),
)

LIST_ORDERS = ToolSpec(
    name="list_orders",
    description="列出当前用户最近订单，可按状态过滤。",
    func=list_orders,
    risk=Risk.READ,
    args_model=ListOrdersArgs,
    timeout_seconds=8,
    max_retries=1,
    summarize=lambda data: f"共 {data.get('total', 0)} 笔订单",
)

GET_LOGISTICS = ToolSpec(
    name="get_logistics",
    description="查询订单物流轨迹与最新动态。",
    func=get_logistics,
    risk=Risk.READ,
    args_model=OrderNoArgs,
    timeout_seconds=8,
    max_retries=1,
    summarize=lambda data: data.get("latestEvent") or data.get("message", "暂无物流信息"),
)

CHECK_REFUND_ELIGIBILITY = ToolSpec(
    name="check_refund_eligibility",
    description="校验订单是否满足退款条件（状态、7 天时间窗、金额阈值）。",
    func=check_refund_eligibility,
    risk=Risk.READ,
    args_model=OrderNoArgs,
    timeout_seconds=8,
    max_retries=0,
    summarize=lambda data: ("符合退款条件" if data.get("eligible") else "不符合退款条件")
    + f"：{data.get('reason', '')}"[:80],
)

__all__ = [
    "CHECK_REFUND_ELIGIBILITY",
    "GET_LOGISTICS",
    "GET_ORDER",
    "LIST_ORDERS",
    "check_refund_eligibility",
    "get_logistics",
    "get_order",
    "list_orders",
    "order_to_dict",
    "refund_amount_of",
]
