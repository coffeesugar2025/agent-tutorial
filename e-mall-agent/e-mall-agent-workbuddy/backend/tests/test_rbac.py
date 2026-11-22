"""权限系统测试：角色权限矩阵、工具过滤、Token 完整性、数据隔离。"""
import pytest

from app.agents.tools import local_tools
from app.domain.models import User
from app.mcp.tools import list_orders
from app.security.rbac import (
    ALL_PERMISSIONS,
    anonymous_user,
    can_access_customer,
    decode_token,
    filter_tools,
    has_permission,
    issue_token,
    permissions_for,
    require_permission,
    set_current_user,
)


def test_role_permission_matrix():
    assert set(permissions_for("admin")) == ALL_PERMISSIONS
    assert "order:create" in permissions_for("customer")
    assert "order:manage" not in permissions_for("customer")
    assert "audit:read" in permissions_for("service")
    assert permissions_for("unknown") == permissions_for("guest")


def test_require_permission_denies_guest():
    with pytest.raises(PermissionError, match="order:read"):
        require_permission(anonymous_user(), "order:read")
    assert has_permission(anonymous_user(), "product:read")


def test_tool_filtering_by_role():
    tools = local_tools()
    customer = User(id="U001", name="张三", role="customer")
    guest_tools = {t.name for t in filter_tools(tools, anonymous_user())}
    customer_tools = {t.name for t in filter_tools(tools, customer)}
    assert guest_tools == {"search_products", "get_product", "check_inventory", "rag_search"}
    assert "create_order" in customer_tools
    assert "create_order" not in guest_tools


def test_token_issue_and_tamper_detection():
    user = User(id="U001", name="张三", role="customer")
    token = issue_token(user, "test-secret", ttl=60)
    payload = decode_token(token, "test-secret")
    assert payload and payload["sub"] == "U001" and payload["role"] == "customer"
    assert decode_token(token, "wrong-secret") is None
    assert decode_token(token + "tampered", "test-secret") is None


def test_customer_scope():
    customer = User(id="U001", name="张三", role="customer")
    service = User(id="S001", name="王客服", role="service")
    assert can_access_customer(customer, "U001")
    assert not can_access_customer(customer, "U002")
    assert can_access_customer(service, "U002")


def test_tool_enforces_customer_scope():
    set_current_user(User(id="U001", name="张三", role="customer"))
    result = list_orders("U002")
    assert "permission_denied" in result
