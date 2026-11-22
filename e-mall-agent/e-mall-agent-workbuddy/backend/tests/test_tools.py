"""MCP/业务工具测试：商品、库存、订单、退款、知识库，以及权限拦截。"""
import json
import os
import sys
from pathlib import Path

import pytest

from app.domain.models import User
from app.domain.repository import get_repository
from app.mcp.server import mcp
from app.mcp.tools import (
    ALL_TOOL_FUNCTIONS,
    check_inventory,
    create_order,
    get_order,
    initiate_refund,
    list_orders,
    rag_search,
    search_products,
)
from app.security.audit import get_audit_logger
from app.security.rbac import set_current_user


def test_mcp_server_registers_all_tools():
    assert mcp.name == "ecommerce-tools"
    assert len(ALL_TOOL_FUNCTIONS) == 8
    assert {fn.__name__ for fn in ALL_TOOL_FUNCTIONS} == {
        "search_products", "get_product", "check_inventory", "create_order",
        "list_orders", "get_order", "initiate_refund", "rag_search",
    }


def test_search_and_inventory():
    set_current_user(User(id="U001", name="张三", role="customer"))
    products = json.loads(search_products("降噪耳机"))
    assert products and products[0]["id"] == "P001"
    inventory = json.loads(check_inventory("P001"))
    assert inventory["available"] is True and inventory["stock"] == 12


def test_create_order_decreases_stock_and_audits():
    set_current_user(User(id="U001", name="张三", role="customer"))
    order = json.loads(create_order("U001", json.dumps([{"product_id": "P008", "quantity": 2}])))
    assert order["status"] == "created"
    assert order["total"] == 258.0
    assert get_repository().get_product("P008").stock == 98
    assert any(e["action"] == "tool.create_order" for e in get_audit_logger().query())


def test_order_scope_and_refund():
    set_current_user(User(id="U002", name="李四", role="customer"))
    denied = json.loads(get_order("O1001"))
    assert denied.get("permission_denied")
    own = json.loads(get_order("O1002"))
    assert own["id"] == "O1002"
    refund = json.loads(initiate_refund("O1002", "不想要了"))
    assert refund["status"] == "refund_requested"
    assert json.loads(list_orders("U002"))[0]["status"] == "refund_requested"


def test_rag_tool():
    set_current_user(User(id="U001", name="张三", role="customer"))
    docs = json.loads(rag_search("退款多久到账"))
    assert any("退款" in doc["content"] for doc in docs)


@pytest.mark.asyncio
async def test_real_mcp_stdio_roundtrip():
    """真正走一次 MCP 协议：MultiServerMCPClient -> FastMCP -> ListTools/CallTool。"""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    env = dict(os.environ)
    backend_dir = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = backend_dir + os.pathsep + env.get("PYTHONPATH", "")
    client = MultiServerMCPClient({
        "ecommerce": {"transport": "stdio", "command": sys.executable,
                      "args": ["-m", "app.mcp.server"], "env": env}
    })
    tools = await client.get_tools()
    assert len(tools) == 8
    assert "search_products" in {t.name for t in tools}
    tool = next(t for t in tools if t.name == "search_products")
    result = await tool.ainvoke({"query": "耳机"})
    assert "P001" in str(result)
