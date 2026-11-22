"""Business tools exposed through MCP and to LangChain agents.

These functions are the single source of truth: the standalone FastMCP server
registers them, and the in-process adapter wraps the very same functions.
"""
from __future__ import annotations

import json
from typing import Any

from ..domain.repository import get_repository
from ..rag.pipeline import get_rag_pipeline
from ..security.audit import get_audit_logger
from ..security.rbac import (
    can_access_customer,
    get_current_user,
    has_permission,
    require_customer_scope,
    require_permission,
)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _deny(action: str, resource: str, message: str) -> str:
    get_audit_logger().record(get_current_user().id, action, resource, "deny", message)
    return _json({"error": message, "permission_denied": True})


def search_products(query: str) -> str:
    """按关键词搜索在售商品，返回商品 id、名称、价格与库存。query 可为商品名、品类或需求描述。"""
    if not has_permission(get_current_user(), "product:read"):
        return _deny("tool.search_products", query, "缺少商品读取权限")
    products = get_repository().search_products(query)
    return _json([p.model_dump() for p in products])


def get_product(product_id: str) -> str:
    """根据商品 id 获取商品详情。"""
    if not has_permission(get_current_user(), "product:read"):
        return _deny("tool.get_product", product_id, "缺少商品读取权限")
    product = get_repository().get_product(product_id)
    return _json(product.model_dump()) if product else _json({"error": "商品不存在"})


def check_inventory(product_id: str) -> str:
    """查询指定商品的实时库存是否充足。"""
    if not has_permission(get_current_user(), "product:read"):
        return _deny("tool.check_inventory", product_id, "缺少商品读取权限")
    info = get_repository().get_inventory(product_id)
    return _json(info) if info else _json({"error": "商品不存在"})


def create_order(customer_id: str, items_json: str) -> str:
    """为客户下单。items_json 是 JSON 字符串，形如 [{"product_id":"P001","quantity":1}]。"""
    actor = get_current_user()
    if not has_permission(actor, "order:create") or not can_access_customer(actor, customer_id):
        return _deny("tool.create_order", customer_id, "无权为该客户下单")
    try:
        items = json.loads(items_json)
        if not isinstance(items, list):
            raise ValueError("items_json 必须是数组")
        order = get_repository().create_order(customer_id, items)
    except Exception as exc:
        return _json({"error": str(exc)})
    get_audit_logger().record(actor.id, "tool.create_order", order.id, "allow",
                              f"total={order.total}")
    return _json(order.model_dump())


def list_orders(customer_id: str) -> str:
    """列出指定客户的订单；客服/管理员可查看全部，普通客户仅能查看自己的订单。"""
    actor = get_current_user()
    if not has_permission(actor, "order:read"):
        return _deny("tool.list_orders", customer_id, "缺少订单读取权限")
    if not can_access_customer(actor, customer_id):
        return _deny("tool.list_orders", customer_id, "越权访问他人订单")
    orders = get_repository().list_orders(customer_id)
    get_audit_logger().record(actor.id, "tool.list_orders", customer_id, "allow",
                              f"count={len(orders)}")
    return _json([o.model_dump() for o in orders])


def get_order(order_id: str) -> str:
    """根据订单 id 查询订单明细与状态。"""
    actor = get_current_user()
    if not has_permission(actor, "order:read"):
        return _deny("tool.get_order", order_id, "缺少订单读取权限")
    order = get_repository().get_order(order_id)
    if not order:
        return _json({"error": "订单不存在"})
    if not can_access_customer(actor, order.customer_id):
        return _deny("tool.get_order", order_id, "越权访问他人订单")
    get_audit_logger().record(actor.id, "tool.get_order", order_id, "allow")
    return _json(order.model_dump())


def initiate_refund(order_id: str, reason: str) -> str:
    """为订单发起退款申请；会校验订单归属与退款权限。"""
    actor = get_current_user()
    if not has_permission(actor, "order:refund"):
        return _deny("tool.initiate_refund", order_id, "缺少退款权限")
    order = get_repository().get_order(order_id)
    if not order:
        return _json({"error": "订单不存在"})
    if not can_access_customer(actor, order.customer_id):
        return _deny("tool.initiate_refund", order_id, "越权操作他人订单")
    updated = get_repository().request_refund(order_id, reason)
    get_audit_logger().record(actor.id, "tool.initiate_refund", order_id, "allow", reason)
    return _json({"order_id": order_id, "status": updated.status if updated else "unknown",
                  "reason": reason})


def rag_search(query: str) -> str:
    """检索售后、配送、优惠、发票等知识库政策，返回最相关的条目。"""
    if not has_permission(get_current_user(), "chat:use"):
        return _deny("tool.rag_search", query, "缺少对话权限")
    docs = get_rag_pipeline().retrieve(query)
    return _json([{"source": d["source"], "content": d["content"]} for d in docs])


ALL_TOOL_FUNCTIONS = [
    search_products, get_product, check_inventory, create_order,
    list_orders, get_order, initiate_refund, rag_search,
]
TOOL_FUNCTIONS_BY_NAME = {fn.__name__: fn for fn in ALL_TOOL_FUNCTIONS}
