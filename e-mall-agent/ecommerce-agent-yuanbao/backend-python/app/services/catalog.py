"""电商领域数据 + 业务规则（纯 Python，无框架依赖）。

这一层是 MCP Server 与单元测试共同依赖的真相源：
MCP 只负责把这里的能力暴露成标准工具，业务规则不写在提示词里。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "SKU-1001", "name": "星野 Pro 降噪耳机", "category": "数码",
        "brand": "星野", "price": 899.0, "stock": 42, "rating": 4.8,
        "tags": ["降噪", "蓝牙5.4", "续航40h"],
        "specs": {"颜色": "雾灰", "保修": "2年"},
        "description": "主动降噪深度 45dB，适合通勤与办公。",
    },
    {
        "sku": "SKU-1002", "name": "星野 Lite 无线耳机", "category": "数码",
        "brand": "星野", "price": 399.0, "stock": 156, "rating": 4.5,
        "tags": ["轻量", "蓝牙5.3", "续航28h"],
        "specs": {"颜色": "奶白", "保修": "1年"},
        "description": "入门轻量款，单耳仅 4.1g。",
    },
    {
        "sku": "SKU-2001", "name": "云朵 记忆棉护颈枕", "category": "家居",
        "brand": "云朵", "price": 169.0, "stock": 0, "rating": 4.6,
        "tags": ["慢回弹", "可拆洗"],
        "specs": {"尺寸": "50x30cm", "保修": "1年"},
        "description": "人体工学曲线，配可拆洗针织枕套。",
    },
    {
        "sku": "SKU-2002", "name": "云朵 乳胶枕 一对装", "category": "家居",
        "brand": "云朵", "price": 329.0, "stock": 88, "rating": 4.7,
        "tags": ["泰国乳胶", "一对装", "透气"],
        "specs": {"尺寸": "60x40cm", "保修": "3年"},
        "description": "93% 天然乳胶含量，双面蜂窝透气孔。",
    },
    {
        "sku": "SKU-3001", "name": "轻风 便携挂脖风扇", "category": "数码",
        "brand": "轻风", "price": 129.0, "stock": 320, "rating": 4.3,
        "tags": ["无叶", "USB-C", "三档"],
        "specs": {"颜色": "薄荷绿", "保修": "1年"},
        "description": "无叶设计不绞发，最长续航 12 小时。",
    },
    {
        "sku": "SKU-3002", "name": "轻风 桌面循环扇", "category": "家居",
        "brand": "轻风", "price": 259.0, "stock": 61, "rating": 4.4,
        "tags": ["静音", "直流变频"],
        "specs": {"颜色": "白", "保修": "2年"},
        "description": "22dB 静音直流电机，支持 8 档风速。",
    },
    {
        "sku": "SKU-4001", "name": "拾光 机械键盘 87 键", "category": "数码",
        "brand": "拾光", "price": 549.0, "stock": 27, "rating": 4.9,
        "tags": ["热插拔", "Gasket", "三模"],
        "specs": {"轴体": "线性轴", "保修": "1年"},
        "description": "Gasket 结构 + 三模连接，支持全键热插拔。",
    },
    {
        "sku": "SKU-4002", "name": "拾光 人体工学椅垫", "category": "家居",
        "brand": "拾光", "price": 219.0, "stock": 74, "rating": 4.2,
        "tags": ["凝胶", "减压"],
        "specs": {"尺寸": "45x42cm", "保修": "1年"},
        "description": "凝胶 + 记忆棉双层，久坐减压。",
    },
]

COUPONS: list[dict[str, Any]] = [
    {"code": "FULL100", "type": "full_reduce", "title": "满 500 减 100", "threshold": 500.0, "value": 100.0},
    {"code": "FULL30", "type": "full_reduce", "title": "满 200 减 30", "threshold": 200.0, "value": 30.0},
    {"code": "DIGI9", "type": "discount", "title": "数码 9 折", "threshold": 0.0, "value": 0.9, "scope": "数码", "cap": 80.0},
    {"code": "NEW50", "type": "full_reduce", "title": "新人满 300 减 50", "threshold": 300.0, "value": 50.0},
]

_ORDERS: list[dict[str, Any]] = [
    {
        "order_id": "EC20261118001", "user_id": "u_1001",
        "items": [{"sku": "SKU-1001", "name": "星野 Pro 降噪耳机", "qty": 1, "price": 899.0}],
        "total": 799.0, "status": "运输中",
        "created_at": "2026-11-18 10:24:00",
        "logistics": {"carrier": "顺丰速运", "tracking_no": "SF1234567890", "node": "已到达苏州中转场"},
        "paid": True,
    },
    {
        "order_id": "EC20261105002", "user_id": "u_1001",
        "items": [{"sku": "SKU-4001", "name": "拾光 机械键盘 87 键", "qty": 1, "price": 549.0}],
        "total": 519.0, "status": "已签收",
        "created_at": "2026-11-05 19:02:00",
        "logistics": {"carrier": "京东物流", "tracking_no": "JD9876543210", "node": "已签收"},
        "paid": True,
    },
    {
        "order_id": "EC20261120003", "user_id": "u_1001",
        "items": [{"sku": "SKU-3001", "name": "轻风 便携挂脖风扇", "qty": 2, "price": 129.0}],
        "total": 228.0, "status": "待付款",
        "created_at": "2026-11-20 08:11:00",
        "logistics": {"carrier": "", "tracking_no": "", "node": "待发货"},
        "paid": False,
    },
    {
        "order_id": "EC20261101004", "user_id": "u_2002",
        "items": [{"sku": "SKU-2002", "name": "云朵 乳胶枕 一对装", "qty": 1, "price": 329.0}],
        "total": 299.0, "status": "已签收",
        "created_at": "2026-11-01 14:30:00",
        "logistics": {"carrier": "中通", "tracking_no": "ZT0001112223", "node": "已签收"},
        "paid": True,
    },
]

POLICIES: dict[str, str] = {
    "退货": "自签收之日起 7 天内可无理由退货（商品未激活、配件齐全）；数码类需保留原包装。",
    "换货": "签收 15 天内出现非人为质量问题可换货，运费由商家承担。",
    "价保": "下单后 15 天内同款降价可申请价保，返还差价至原支付账户。",
    "发票": "订单完成后可在「我的-发票管理」开具电子增值税普通发票，支持抬头修改一次。",
    "保修": "按商品详情页标注保修期执行，以订单完成时间为起算点。",
}


def _ok(**payload: Any) -> dict[str, Any]:
    return {"ok": True, **payload}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def search_products(
    keyword: str = "",
    category: str | None = None,
    max_price: float | None = None,
    min_price: float | None = None,
    sort_by: str = "relevance",
    limit: int = 5,
) -> dict[str, Any]:
    """按关键词 / 类目 / 价格区间检索商品，返回候选商品列表。"""
    kw = (keyword or "").strip().lower()
    rows = list(PRODUCTS)
    if kw:
        rows = [
            p for p in rows
            if kw in p["name"].lower()
            or kw in p["brand"].lower()
            or kw in p["category"].lower()
            or any(kw in t.lower() for t in p["tags"])
            or kw in p["sku"].lower()
            or kw in p["description"].lower()
        ]
    if category:
        rows = [p for p in rows if p["category"] == category]
    if max_price is not None:
        rows = [p for p in rows if p["price"] <= float(max_price)]
    if min_price is not None:
        rows = [p for p in rows if p["price"] >= float(min_price)]

    if sort_by == "price_asc":
        rows.sort(key=lambda p: p["price"])
    elif sort_by == "price_desc":
        rows.sort(key=lambda p: -p["price"])
    elif sort_by == "rating":
        rows.sort(key=lambda p: -p["rating"])
    else:
        rows.sort(key=lambda p: (-p["rating"], -p["stock"]))

    limit = max(1, min(int(limit), 20))
    return _ok(
        keyword=keyword, total=len(rows),
        products=[_public_product(p) for p in rows[:limit]],
    )


def _public_product(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "sku": p["sku"], "name": p["name"], "category": p["category"],
        "brand": p["brand"], "price": p["price"], "stock": p["stock"],
        "in_stock": p["stock"] > 0, "rating": p["rating"],
        "tags": p["tags"], "description": p["description"],
    }


def get_product(sku: str) -> dict[str, Any]:
    """按 SKU 查询单个商品详情（含规格参数）。"""
    for p in PRODUCTS:
        if p["sku"] == sku:
            return _ok(product={**_public_product(p), "specs": p["specs"]})
    return _err(f"未找到商品 {sku}")


def check_inventory(sku: str) -> dict[str, Any]:
    """查询指定 SKU 的实时可用库存。"""
    for p in PRODUCTS:
        if p["sku"] == sku:
            return _ok(sku=sku, name=p["name"], stock=p["stock"], in_stock=p["stock"] > 0)
    return _err(f"未找到商品 {sku}")


def get_order(order_id: str, user_id: str | None = None) -> dict[str, Any]:
    """按订单号查询订单状态、金额与物流节点；传 user_id 时做归属校验。"""
    for o in _ORDERS:
        if o["order_id"] == order_id:
            if user_id and o["user_id"] != user_id:
                return _err("无权查看该订单：订单归属校验未通过")
            return _ok(order=dict(o))
    return _err(f"未找到订单 {order_id}")


def list_user_orders(user_id: str, limit: int = 5) -> dict[str, Any]:
    """列出指定用户最近的订单（默认 5 条）。"""
    rows = [dict(o) for o in _ORDERS if o["user_id"] == user_id]
    rows.sort(key=lambda o: o["created_at"], reverse=True)
    return _ok(user_id=user_id, total=len(rows), orders=rows[: max(1, min(int(limit), 20))])


def list_coupons(user_id: str | None = None) -> dict[str, Any]:
    """列出当前可用优惠券（含门槛与面额）。"""
    return _ok(user_id=user_id, coupons=[dict(c) for c in COUPONS])


def _coupon_by_code(code: str) -> dict[str, Any] | None:
    return next((c for c in COUPONS if c["code"].upper() == code.upper()), None)


def calculate_price(sku: str, quantity: int = 1, coupon_code: str | None = None) -> dict[str, Any]:
    """计算到手价：校验库存 → 叠加优惠券 → 输出优惠拆解。不产生真实交易。"""
    product = next((p for p in PRODUCTS if p["sku"] == sku), None)
    if not product:
        return _err(f"未找到商品 {sku}")
    qty = max(1, int(quantity))
    if product["stock"] < qty:
        return _err(f"库存不足：{product['name']} 仅剩 {product['stock']} 件")

    subtotal = round(product["price"] * qty, 2)
    discount = 0.0
    applied: list[dict[str, Any]] = []
    if coupon_code:
        coupon = _coupon_by_code(coupon_code)
        if not coupon:
            return _err(f"优惠券 {coupon_code} 不存在或已失效")
        if subtotal < coupon["threshold"]:
            return _err(f"未达门槛：{coupon['title']} 需满 {coupon['threshold']} 元，当前 {subtotal} 元")
        if coupon.get("scope") and product["category"] != coupon["scope"]:
            return _err(f"优惠券 {coupon_code} 仅限 {coupon['scope']} 类目使用")
        if coupon["type"] == "full_reduce":
            discount = float(coupon["value"])
        else:
            discount = round(subtotal * (1 - float(coupon["value"])), 2)
            discount = min(discount, float(coupon.get("cap", discount)))
        applied.append({"code": coupon["code"], "title": coupon["title"], "amount": round(discount, 2)})

    return _ok(
        sku=sku, name=product["name"], quantity=qty,
        unit_price=product["price"], subtotal=subtotal,
        coupons=applied, total_discount=round(discount, 2),
        payable=round(subtotal - discount, 2), currency="CNY",
    )


def get_after_sale_policy(topic: str = "退货") -> dict[str, Any]:
    """查询售后政策：退货 / 换货 / 价保 / 发票 / 保修。"""
    hit = next((k for k in POLICIES if k in topic or topic in k), None)
    if not hit:
        return _ok(topic=topic, matched=False, available_topics=list(POLICIES), content="")
    return _ok(topic=hit, matched=True, content=POLICIES[hit])


def check_after_sale_eligibility(order_id: str, user_id: str | None = None) -> dict[str, Any]:
    """按「签收 7 天内 + 已付款」规则判断订单是否可无理由退货。"""
    found = get_order(order_id, user_id)
    if not found["ok"]:
        return found
    order = found["order"]
    if not order["paid"]:
        return _ok(order_id=order_id, eligible=False, reason="订单未付款，无法申请退货")
    if order["status"] != "已签收":
        return _ok(order_id=order_id, eligible=False, reason=f"订单状态为「{order['status']}」，需签收后申请")
    signed_at = datetime.strptime(order["created_at"], "%Y-%m-%d %H:%M:%S") + timedelta(days=3)
    days_left = max(0, 7 - (datetime(2026, 11, 22) - signed_at).days)
    return _ok(
        order_id=order_id, eligible=days_left > 0,
        reason="签收 7 天内" if days_left > 0 else "已超出 7 天无理由期",
        days_left=days_left, policy=POLICIES["退货"],
        items=order["items"],
    )


def recommend_products(budget: float = 1000.0, category: str | None = None, preference: str = "") -> dict[str, Any]:
    """基于预算、类目和偏好做规则推荐（可替换为向量检索 / 召回服务）。"""
    kw = (preference or "").strip()
    pool = [
        p for p in PRODUCTS
        if p["stock"] > 0 and p["price"] <= float(budget)
        and (not category or p["category"] == category)
        and (not kw or kw in p["name"] or kw in p["category"] or any(kw in t for t in p["tags"]))
    ]
    pool.sort(key=lambda p: (-p["rating"], p["price"]))
    picks = pool[:3]
    return _ok(
        budget=budget, category=category, preference=preference,
        total=len(pool), products=[_public_product(p) for p in picks],
        reason="按「评分优先 + 预算内 + 有货」规则召回",
    )
