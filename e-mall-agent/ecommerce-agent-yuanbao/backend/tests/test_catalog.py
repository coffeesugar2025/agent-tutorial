"""领域业务规则单测：不依赖 LangChain / MCP / 网络，CI 中最快的一层。"""
from __future__ import annotations

import pytest

from app.services import catalog


def test_search_by_keyword_and_price():
    r = catalog.search_products("耳机", max_price=500.0)
    assert r["ok"] is True
    assert r["total"] == 1
    assert r["products"][0]["sku"] == "SKU-1002"
    assert r["products"][0]["price"] == 399.0


def test_search_sorting_and_limit():
    r = catalog.search_products(sort_by="price_asc", limit=3)
    prices = [p["price"] for p in r["products"]]
    assert prices == sorted(prices)
    assert len(prices) == 3
    assert all(p["in_stock"] == (p["stock"] > 0) for p in r["products"])


def test_search_no_match():
    r = catalog.search_products("不存在的商品XYZ")
    assert r["ok"] is True and r["total"] == 0 and r["products"] == []


def test_get_product_includes_specs():
    r = catalog.get_product("SKU-1001")
    assert r["ok"] is True
    assert r["product"]["specs"]["保修"] == "2年"
    assert catalog.get_product("SKU-9999")["ok"] is False


def test_check_inventory_out_of_stock():
    r = catalog.check_inventory("SKU-2001")
    assert r["ok"] is True and r["stock"] == 0 and r["in_stock"] is False


def test_get_order_ownership_check():
    assert catalog.get_order("EC20261118001", "u_1001")["ok"] is True
    denied = catalog.get_order("EC20261118001", "u_9999")
    assert denied["ok"] is False and "无权" in denied["error"]
    assert catalog.get_order("EC-NOT-EXIST")["ok"] is False


def test_list_user_orders_is_scoped():
    r = catalog.list_user_orders("u_1001", limit=2)
    assert r["total"] == 3 and len(r["orders"]) == 2
    assert all(o["user_id"] == "u_1001" for o in r["orders"])
    assert r["orders"][0]["order_id"] >= r["orders"][1]["order_id"]


@pytest.mark.parametrize(
    "sku,qty,code,expected",
    [
        ("SKU-1001", 1, None, 899.0),
        ("SKU-1001", 1, "FULL100", 799.0),
        ("SKU-3001", 2, "FULL30", 228.0),
        ("SKU-1001", 1, "DIGI9", 819.0),  # 数码 9 折，封顶 80
    ],
)
def test_calculate_price(sku, qty, code, expected):
    r = catalog.calculate_price(sku, qty, code)
    assert r["ok"] is True
    assert r["payable"] == expected
    assert r["subtotal"] - r["total_discount"] == expected


def test_price_coupon_threshold_and_scope_and_cap():
    assert "未达门槛" in catalog.calculate_price("SKU-3001", 1, "FULL100")["error"]
    assert "仅限" in catalog.calculate_price("SKU-2002", 1, "DIGI9")["error"]
    assert "不存在" in catalog.calculate_price("SKU-1001", 1, "BAD")["error"]
    capped = catalog.calculate_price("SKU-4001", 1, "DIGI9")
    assert capped["total_discount"] == 54.9  # 549 * 0.1，未触及 80 封顶
    big = catalog.calculate_price("SKU-1001", 1, "DIGI9")
    assert big["total_discount"] == 80.0  # 触发封顶


def test_price_rejects_oversell():
    r = catalog.calculate_price("SKU-1001", 999)
    assert r["ok"] is False and "库存不足" in r["error"]
    assert catalog.calculate_price("SKU-2001", 1)["ok"] is False


def test_after_sale_policy_and_eligibility():
    policy = catalog.get_after_sale_policy("价保")
    assert policy["matched"] is True and "15 天" in policy["content"]
    assert catalog.get_after_sale_policy("量子纠缠")["available_topics"]

    ok = catalog.check_after_sale_eligibility("EC20261105002", "u_1001")
    assert ok["ok"] is True and "eligible" in ok
    assert catalog.check_after_sale_eligibility("EC20261120003")["eligible"] is False  # 未付款
    assert catalog.check_after_sale_eligibility("EC20261118001")["eligible"] is False  # 未签收


def test_recommend_only_in_stock_and_within_budget():
    r = catalog.recommend_products(budget=300.0, category="数码")
    assert r["ok"] is True
    assert all(p["price"] <= 300.0 and p["in_stock"] for p in r["products"])
    assert r["reason"]
    empty = catalog.recommend_products(budget=1.0)
    assert empty["total"] == 0 and empty["products"] == []


def test_all_prices_are_positive_and_skus_unique():
    skus = [p["sku"] for p in catalog.PRODUCTS]
    assert len(skus) == len(set(skus))
    assert all(p["price"] > 0 for p in catalog.PRODUCTS)
