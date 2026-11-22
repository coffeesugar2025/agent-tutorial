"""多智能体测试：意图路由、 specialist 工具调用、流式事件、链路追踪。"""
import pytest

from app.agents.supervisor import classify_route, run_agent, stream_agent
from app.domain.models import User
from app.domain.repository import get_repository
from app.llm.factory import RuleBasedChatModel
from app.observability.tracer import get_tracer
from app.security.rbac import set_current_user

USER = User(id="U001", name="张三", role="customer")


@pytest.fixture(autouse=True)
def acting_user():
    set_current_user(USER)


def test_intent_classification():
    assert classify_route("推荐一款耳机") == "shopping"
    assert classify_route("我的订单在哪里") == "order"
    assert classify_route("O1001 申请退款") == "support"
    assert classify_route("保修政策是什么") == "support"
    assert classify_route("你好") == "general"


def test_offline_model_tool_selection():
    assert RuleBasedChatModel.pick_tool("查一下 P001 库存") == "check_inventory"
    assert RuleBasedChatModel.pick_tool("我要下单买键盘") == "create_order"
    assert RuleBasedChatModel.pick_tool("我的订单") == "list_orders"
    assert RuleBasedChatModel.pick_tool("退货流程") == "rag_search"


@pytest.mark.asyncio
async def test_shopping_agent_recommends_real_product():
    result = await run_agent("推荐降噪耳机", USER, "t-shopping")
    assert result["route"] == "shopping"
    assert "P001" in result["answer"]
    assert "899" in result["answer"]


@pytest.mark.asyncio
async def test_order_agent_lists_scoped_orders():
    result = await run_agent("我的订单", USER, "t-order")
    assert result["route"] == "order"
    assert "O1001" in result["answer"]
    assert "O1002" not in result["answer"]


@pytest.mark.asyncio
async def test_support_agent_applies_refund():
    result = await run_agent("O1003 想退货退款", USER, "t-support")
    assert result["route"] == "support"
    assert "退款" in result["answer"]
    assert get_repository().get_order("O1003").status == "refund_requested"


@pytest.mark.asyncio
async def test_stream_emits_node_route_and_answer():
    events = [event async for event in stream_agent("我的订单", USER, "t-stream")]
    kinds = {e["event"] for e in events}
    assert {"node", "route", "token", "done"} <= kinds
    assert any(e.get("node") == "context" for e in events if e["event"] == "node")
    assert "O1001" in next(e["data"] for e in events if e["event"] == "done")


@pytest.mark.asyncio
async def test_tracer_records_tool_calls():
    await run_agent("推荐耳机", USER, "t-trace")
    events = get_tracer().query(trace_id="t-trace")
    assert any(e["node"] == "context" for e in events)
    assert any(e["event"] == "search_products" for e in events)
