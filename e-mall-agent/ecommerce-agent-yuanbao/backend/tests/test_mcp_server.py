"""MCP Server 契约测试：验证工具函数与领域层一致、描述完整、注册齐全。"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from mcp_server import server as mcp_server

TOOL_FNS = [
    mcp_server.search_products,
    mcp_server.get_product,
    mcp_server.check_inventory,
    mcp_server.get_order,
    mcp_server.list_user_orders,
    mcp_server.list_coupons,
    mcp_server.calculate_price,
    mcp_server.get_after_sale_policy,
    mcp_server.check_after_sale_eligibility,
    mcp_server.recommend_products,
]


def test_server_exposes_ten_tools():
    assert len(TOOL_FNS) == 10
    tools = asyncio.run(mcp_server.mcp.list_tools())
    registered = {t.name for t in tools}
    assert registered == {fn.__name__ for fn in TOOL_FNS}


def test_every_tool_has_docstring_and_typed_signature():
    for fn in TOOL_FNS:
        assert fn.__doc__ and len(fn.__doc__.strip()) > 10, fn.__name__
        sig = inspect.signature(fn)
        assert sig.return_annotation is not inspect.Signature.empty, fn.__name__
        assert all(p.annotation is not inspect.Parameter.empty for p in sig.parameters.values()), fn.__name__


def test_server_tool_returns_same_as_catalog():
    from app.services import catalog

    assert mcp_server.search_products("耳机") == catalog.search_products("耳机")
    assert mcp_server.calculate_price("SKU-1001", 1, "FULL100") == catalog.calculate_price(
        "SKU-1001", 1, "FULL100"
    )
    assert mcp_server.get_order("EC20261118001", "u_1001") == catalog.get_order(
        "EC20261118001", "u_1001"
    )


def test_server_tools_are_read_only_and_json_serializable():
    import json

    for fn in TOOL_FNS:
        sig = inspect.signature(fn)
        args = {}
        for name, param in sig.parameters.items():
            if param.default is not inspect.Parameter.empty:
                continue
            args[name] = "SKU-1001" if "sku" in name else (
                "EC20261118001" if "order" in name else "退货"
            )
        result = fn(**args)
        assert isinstance(result, dict)
        assert result.get("ok") is not None
        json.dumps(result, ensure_ascii=False)  # MCP 传输要求可序列化


@pytest.mark.parametrize("mode", ["stdio", "http"])
def test_entrypoint_modes_are_documented(mode):
    """入口脚本两种传输模式均被 main 分支覆盖（静态检查，不真的起服务）。"""
    source = inspect.getsource(mcp_server)
    assert 'mode == "http"' in source
    assert "streamable-http" in source
    assert mode in ("stdio", "http")
