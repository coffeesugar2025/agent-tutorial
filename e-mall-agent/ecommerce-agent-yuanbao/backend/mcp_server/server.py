"""电商 MCP Server（FastMCP）。

两种启动方式，对应后端 MCP_TRANSPORT：
  python3 mcp_server/server.py            -> stdio（由 MCPAdapter 拉起子进程）
  python3 mcp_server/server.py http       -> Streamable HTTP :9000/mcp

注意：业务规则全部在 app.services.catalog，本文件只做协议暴露，
因此任何 MCP 客户端（Claude Desktop / Cursor / 自研 Agent）都能复用同一套能力。
"""
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastmcp import FastMCP

from app.services import catalog

mcp = FastMCP("ecommerce-shop")


def search_products(
    keyword: str = "",
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    sort_by: str = "relevance",
    limit: int = 5,
) -> dict[str, Any]:
    """检索商品。支持关键词、类目、价格区间与排序（price_asc/price_desc/rating/relevance）。
    返回候选商品的 SKU、名称、价格、库存、评分与标签。找商品/比价/推荐前先调用本工具。"""
    return catalog.search_products(keyword, category, max_price, min_price, sort_by, limit)


def get_product(sku: str) -> dict[str, Any]:
    """按 SKU 查询单个商品详情，包含规格参数。用户追问某款商品细节时调用。"""
    return catalog.get_product(sku)


def check_inventory(sku: str) -> dict[str, Any]:
    """查询指定 SKU 的实时可用库存与是否有货。用户问「还有货吗/能买几件」时调用。"""
    return catalog.check_inventory(sku)


def get_order(order_id: str, user_id: str | None = None) -> dict[str, Any]:
    """按订单号查询订单状态、金额、商品与物流节点。
    user_id 用于归属校验，必须传当前登录用户；查不到会返回错误。"""
    return catalog.get_order(order_id, user_id)


def list_user_orders(user_id: str, limit: int = 5) -> dict[str, Any]:
    """列出某用户最近订单。用户说「我的订单」但没给订单号时调用。"""
    return catalog.list_user_orders(user_id, limit)


def list_coupons(user_id: str | None = None) -> dict[str, Any]:
    """列出当前可用优惠券及门槛、面额、适用类目。用户问「有什么券」时调用。"""
    return catalog.list_coupons(user_id)


def calculate_price(sku: str, quantity: int = 1, coupon_code: str | None = None) -> dict[str, Any]:
    """计算到手价：校验库存后叠加优惠券，返回原价、优惠拆解与 payable 应付金额。
    用户问「多少钱/用券后多少/买两件」时调用。只读计算，不会下单。"""
    return catalog.calculate_price(sku, quantity, coupon_code)


def get_after_sale_policy(topic: str = "退货") -> dict[str, Any]:
    """查询售后政策原文。topic 支持：退货、换货、价保、发票、保修。"""
    return catalog.get_after_sale_policy(topic)


def check_after_sale_eligibility(order_id: str, user_id: str | None = None) -> dict[str, Any]:
    """判断某订单是否符合 7 天无理由退货条件，返回 eligible、剩余天数与政策依据。"""
    return catalog.check_after_sale_eligibility(order_id, user_id)


def recommend_products(
    budget: float = 1000.0,
    category: str | None = None,
    preference: str = "",
) -> dict[str, Any]:
    """按预算、类目、偏好做规则推荐，返回最多 3 个有货商品及推荐理由。"""
    return catalog.recommend_products(budget, category, preference)


# 用 mcp.tool(fn) 而非 @mcp.tool 装饰，保留纯函数引用，方便单元测试直接调用。
for _fn in (
    search_products, get_product, check_inventory, get_order, list_user_orders,
    list_coupons, calculate_price, get_after_sale_policy,
    check_after_sale_eligibility, recommend_products,
):
    mcp.tool(_fn)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if mode == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=9000, show_banner=False)
    else:
        mcp.run(transport="stdio", show_banner=False)
