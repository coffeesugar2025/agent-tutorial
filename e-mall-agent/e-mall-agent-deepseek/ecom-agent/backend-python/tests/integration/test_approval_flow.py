"""HITL 审批流集成测试：中断 → 建单 → 授权 → 执行 → 状态机 → 越权拦截。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.common.errors import BizError, Codes
from app.common.ids import new_trace_id
from app.hitl import approval as hitl
from app.infra.db import session_scope
from app.infra.models import ChatSession, OrderInfo, OrderItem, RefundRequest, SysUser
from app.memory import session as session_memory
from app.tools.base import ApprovalRequired, ToolContext, executor
from app.tools.refund_tools import CREATE_REFUND_REQUEST


def _make_user(roles: str = "USER") -> int:
    username = f"c_{uuid.uuid4().hex[:10]}"
    with session_scope() as db:
        row = SysUser(
            username=username,
            password_hash="x",
            display_name="客服测试",
            roles=roles,
            status=1,
        )
        db.add(row)
        db.flush()
        return int(row.id)


def _make_order(user_id: int, amount: float = 3999.0) -> str:
    order_no = f"SO{uuid.uuid4().hex[:12].upper()}"
    with session_scope() as db:
        order = OrderInfo(
            order_no=order_no,
            user_id=user_id,
            status="DELIVERED",
            total_amount=amount,
            pay_amount=amount,
            receiver_name="张三",
            receiver_phone="13800001111",
            receiver_address="上海市浦东新区世纪大道 100 号",
        )
        db.add(order)
        db.flush()
        db.add(
            OrderItem(
                order_id=int(order.id),
                product_id=1,
                sku="PH-001",
                title="测试手机",
                price=amount,
                quantity=1,
            )
        )
    return order_no


def _make_session(user_id: int) -> int:
    return int(session_memory.create_session(user_id, "审批测试")["id"])


def _trigger_approval(user_id: int, session_id: int, order_no: str) -> dict[str, Any]:
    """调用不可逆工具，捕获中断并落成审批任务。"""
    ctx = ToolContext(
        user_id=user_id,
        session_id=session_id,
        trace_id=new_trace_id(),
        agent_type="SERVICE",
    )
    with pytest.raises(ApprovalRequired) as captured:
        asyncio.run(
            executor.execute(
                CREATE_REFUND_REQUEST,
                {"orderNo": order_no, "reason": "买错了，不想要了"},
                ctx,
            )
        )
    task = hitl.approval_from_exception(
        captured.value,
        session_id=session_id,
        user_id=user_id,
        trace_id=ctx.trace_id,
    )
    return task


def test_approval_task_created_with_pending_status():
    user_id = _make_user()
    session_id = _make_session(user_id)
    order_no = _make_order(user_id)

    task = _trigger_approval(user_id, session_id, order_no)

    assert task["status"] == "PENDING"
    assert task["risk"] == "IRREVERSIBLE"
    assert task["actionType"] == "CREATE_REFUND"
    assert task["detail"]["tool"] == "create_refund_request"
    assert task["detail"]["args"]["orderNo"] == order_no
    assert task["expiresAt"]
    assert hitl.pending_count(user_id) == 1


def test_approve_executes_refund_with_approved_status():
    """审批通过后必须真正落退款单，且订单转 REFUNDING。"""
    user_id = _make_user()
    session_id = _make_session(user_id)
    order_no = _make_order(user_id, amount=2999.0)
    task = _trigger_approval(user_id, session_id, order_no)

    result = asyncio.run(hitl.decide(task["id"], user_id, "APPROVE", "同意退款", roles=["USER"]))

    assert result["status"] == "APPROVED"
    assert result["result"]["ok"] is True
    refund_no = result["result"]["refundNo"]
    assert refund_no

    with session_scope() as db:
        refund = db.query(RefundRequest).filter(RefundRequest.refund_no == refund_no).one_or_none()
        assert refund is not None
        # 已审批通过的退款单不应停留在 PENDING_APPROVAL
        assert refund.status == "APPROVED"
        assert float(refund.amount) == 2999.0
        assert refund.approval_id == task["id"]

        order = db.query(OrderInfo).filter(OrderInfo.order_no == order_no).one()
        assert order.status == "REFUNDING"


def test_reject_does_not_create_refund():
    user_id = _make_user()
    session_id = _make_session(user_id)
    order_no = _make_order(user_id)
    task = _trigger_approval(user_id, session_id, order_no)

    result = asyncio.run(hitl.decide(task["id"], user_id, "REJECT", "不符合退款条件", roles=["USER"]))
    assert result["status"] == "REJECTED"

    with session_scope() as db:
        count = db.query(RefundRequest).filter(RefundRequest.user_id == user_id).count()
        assert count == 0
        order = db.query(OrderInfo).filter(OrderInfo.order_no == order_no).one()
        assert order.status == "DELIVERED"


def test_double_decision_is_conflict():
    user_id = _make_user()
    session_id = _make_session(user_id)
    order_no = _make_order(user_id)
    task = _trigger_approval(user_id, session_id, order_no)

    asyncio.run(hitl.decide(task["id"], user_id, "APPROVE", None, roles=["USER"]))
    with pytest.raises(BizError) as captured:
        asyncio.run(hitl.decide(task["id"], user_id, "REJECT", None, roles=["USER"]))
    assert captured.value.code == Codes.CONFLICT


def test_other_user_cannot_decide_without_role():
    owner = _make_user()
    other = _make_user(roles="USER")
    session_id = _make_session(owner)
    task = _trigger_approval(owner, _make_session(owner), _make_order(owner))

    with pytest.raises(BizError) as captured:
        asyncio.run(hitl.decide(task["id"], other, "APPROVE", None, roles=["USER"]))
    # 越权按"不存在"处理，避免枚举他人审批单
    assert captured.value.code == Codes.NOT_FOUND
    assert hitl.get_task(task["id"])["status"] == "PENDING"


def test_admin_can_decide_on_behalf_of_user():
    """客服/运营坐席代客审批是真实业务需求，有 ADMIN 角色即可。"""
    owner = _make_user()
    admin = _make_user(roles="ADMIN")
    task = _trigger_approval(owner, _make_session(owner), _make_order(owner))

    result = asyncio.run(hitl.decide(task["id"], admin, "APPROVE", "坐席代客审批", roles=["ADMIN"]))
    assert result["status"] == "APPROVED"
    assert result["result"]["ok"] is True


def test_expired_task_cannot_be_decided():
    user_id = _make_user()
    session_id = _make_session(user_id)
    order_no = _make_order(user_id)
    task = hitl.create(
        session_id=session_id,
        user_id=user_id,
        action_type="CREATE_REFUND",
        title="过期审批",
        detail={"tool": "create_refund_request", "args": {"orderNo": order_no}, "userId": user_id},
        ttl_seconds=-1,
    )

    expired = hitl.expire_overdue()
    assert expired >= 1
    with pytest.raises(BizError) as captured:
        asyncio.run(hitl.decide(task["id"], user_id, "APPROVE", None, roles=["USER"]))
    assert captured.value.code == Codes.CONFLICT
