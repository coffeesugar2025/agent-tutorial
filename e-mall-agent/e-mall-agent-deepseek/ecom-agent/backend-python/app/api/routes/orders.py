"""订单接口：列表、详情、物流轨迹（严格限定当前登录用户）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_db
from app.common.envelope import ok, page_result
from app.common.errors import not_found
from app.infra.models import Logistics, OrderInfo, OrderItem
from app.security.pii import mask_phone

router = APIRouter(prefix="/orders", tags=["订单"])


def _items_for(db: Session, order_id: int) -> list[dict[str, Any]]:
    rows = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    return [
        {
            "sku": row.sku,
            "title": row.title,
            "price": float(row.price),
            "quantity": row.quantity,
        }
        for row in rows
    ]


def to_vo(db: Session, row: OrderInfo) -> dict[str, Any]:
    """订单对外结构（手机号脱敏）。"""
    return {
        "id": row.id,
        "orderNo": row.order_no,
        "status": row.status,
        "totalAmount": float(row.total_amount),
        "payAmount": float(row.pay_amount),
        "receiverName": row.receiver_name,
        "receiverPhone": mask_phone(row.receiver_phone or "") if row.receiver_phone else None,
        "createdAt": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
        "items": _items_for(db, int(row.id)),
    }


@router.get("", summary="我的订单")
def list_orders(
    status: str | None = Query(default=None, max_length=24),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    query = db.query(OrderInfo).filter(OrderInfo.user_id == user.id)
    if status:
        query = query.filter(OrderInfo.status == status.upper())
    total = query.count()
    rows = (
        query.order_by(OrderInfo.created_at.desc(), OrderInfo.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return ok(page_result([to_vo(db, row) for row in rows], total, page, size))


@router.get("/{order_no}", summary="订单详情")
def get_order(
    order_no: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    row = (
        db.query(OrderInfo)
        .filter(OrderInfo.order_no == order_no, OrderInfo.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        # 不区分"不存在"与"他人订单"，避免订单号枚举
        raise not_found("订单不存在")
    return ok(to_vo(db, row))


@router.get("/{order_no}/logistics", summary="物流轨迹")
def get_logistics(
    order_no: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    order = (
        db.query(OrderInfo)
        .filter(OrderInfo.order_no == order_no, OrderInfo.user_id == user.id)
        .one_or_none()
    )
    if order is None:
        raise not_found("订单不存在")
    row = db.query(Logistics).filter(Logistics.order_id == order.id).one_or_none()
    if row is None:
        return ok({"company": None, "trackingNo": None, "status": "PENDING", "latestEvent": None, "events": []})
    return ok(
        {
            "company": row.company,
            "trackingNo": row.tracking_no,
            "status": row.status,
            "latestEvent": row.latest_event,
            "events": row.events or [],
        }
    )


__all__ = ["router", "to_vo"]
