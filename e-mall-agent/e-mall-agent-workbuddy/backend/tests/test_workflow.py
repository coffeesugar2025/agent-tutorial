"""LangGraph 工作流测试：分支、人工审批中断与恢复、最终状态。"""
import pytest

from app.domain.models import User
from app.domain.repository import get_repository
from app.security.rbac import set_current_user
from app.workflows.fulfillment import resume_fulfillment, run_fulfillment


@pytest.fixture(autouse=True)
def admin():
    set_current_user(User(id="A001", name="管理员", role="admin"))


@pytest.mark.asyncio
async def test_large_order_interrupts_then_completes():
    first = await run_fulfillment("O1001", "U001", "wf-large")
    assert first["status"] == "awaiting_approval"
    assert first["interrupt"]["amount"] == 1098.0

    second = await resume_fulfillment("wf-large", True)
    assert second["status"] == "completed"
    assert get_repository().get_order("O1001").status == "shipped"
    assert "人工审批通过" in second["steps"]


@pytest.mark.asyncio
async def test_rejected_order_is_cancelled():
    await run_fulfillment("O1001", "U001", "wf-reject")
    result = await resume_fulfillment("wf-reject", False)
    assert result["status"] == "cancelled"
    assert get_repository().get_order("O1001").status == "cancelled"


@pytest.mark.asyncio
async def test_small_order_skips_approval():
    order = get_repository().create_order("U001", [{"product_id": "P008", "quantity": 1}])
    result = await run_fulfillment(order.id, "U001", f"wf-{order.id}")
    assert result["status"] == "completed"
    assert "awaiting_approval" != result["status"]


@pytest.mark.asyncio
async def test_missing_order_ends_with_not_found():
    result = await run_fulfillment("O9999", "U001", "wf-missing")
    assert result["status"] == "not_found"
