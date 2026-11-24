"""商品类工具：搜索、详情、对比。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-05] 工具治理
# 职责：商品类工具：搜索、详情、对比
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import Field

from app.common.envelope import CamelModel
from app.infra.db import session_scope
from app.infra.models import Category, Product
from app.tools.base import Risk, ToolContext, ToolSpec

# 检索时忽略的停用词（中文导购高频词，几乎不携带商品语义）
STOPWORDS = {
    "帮我", "我想", "想要", "一个", "一款", "推荐", "一下", "有没有", "什么", "适合",
    "的", "了", "和", "与", "或", "在", "是", "有", "我", "你", "吗", "呢", "请",
    "手机", "商品", "看看", "买", "选", "找", "以内", "以下", "左右", "预算",
}


class SearchProductsArgs(CamelModel):
    query: str = Field(default="", description="自然语言需求，如“拍照好的手机”")
    top_k: int = Field(default=5, ge=1, le=20, description="返回条数")
    max_price: float | None = Field(default=None, ge=0, description="价格上限（元）")
    min_price: float | None = Field(default=None, ge=0, description="价格下限（元）")
    brands: list[str] | None = Field(default=None, description="品牌白名单，如 ['Apple']")
    category_id: int | None = Field(default=None, description="类目 ID")


class ProductDetailArgs(CamelModel):
    sku: str = Field(description="商品 SKU，如 PH-001")


class CompareProductsArgs(CamelModel):
    skus: list[str] = Field(min_length=1, max_length=4, description="要对比的 SKU 列表（2~4 个）")


def _tokens(query: str) -> list[str]:
    """把自然语言需求切成检索词（中文按 2-gram，英文/数字按词）。"""
    if not query:
        return []
    lowered = query.lower()
    ascii_terms = [t for t in re.findall(r"[a-z0-9]{2,}", lowered)]
    cjk = re.sub(r"[^\u4e00-\u9fff]", " ", query)
    grams: list[str] = []
    for chunk in cjk.split():
        if len(chunk) <= 2:
            grams.append(chunk)
        else:
            grams.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    terms = [t for t in [*ascii_terms, *grams] if t and t not in STOPWORDS]
    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return unique[:10]


def product_to_dict(product: Product, category_name: str | None = None) -> dict[str, Any]:
    """ORM → ProductVO 字段（价格转 float，与契约示例一致）。"""
    return {
        "id": product.id,
        "sku": product.sku,
        "title": product.title,
        "subtitle": product.subtitle,
        "brand": product.brand,
        "categoryId": product.category_id,
        "categoryName": category_name,
        "price": round(float(product.price or 0), 2),
        "originalPrice": round(float(product.original_price), 2) if product.original_price else None,
        "stock": product.stock,
        "rating": round(float(product.rating or 0), 1),
        "sales": product.sales,
        "imageUrl": product.image_url,
        "attrs": product.attrs or {},
        "status": product.status,
        "description": product.description,
    }


def _category_names(db: Any, category_ids: set[int]) -> dict[int, str]:
    if not category_ids:
        return {}
    rows = db.query(Category.id, Category.name).filter(Category.id.in_(list(category_ids))).all()
    return {int(row[0]): str(row[1]) for row in rows}


def search_products(
    ctx: ToolContext,
    query: str = "",
    top_k: int = 5,
    max_price: float | None = None,
    min_price: float | None = None,
    brands: list[str] | None = None,
    category_id: int | None = None,
) -> dict[str, Any]:
    """商品搜索：SQL 过滤 + 关键词命中打分（离线可用，等价于"混合检索"里的结构化召回路）。"""
    terms = _tokens(query)
    with session_scope() as db:
        stmt = db.query(Product).filter(Product.status == 1)
        if max_price is not None:
            stmt = stmt.filter(Product.price <= max_price)
        if min_price is not None:
            stmt = stmt.filter(Product.price >= min_price)
        if brands:
            lowered = [b.lower() for b in brands]
            stmt = stmt.filter(Product.brand.isnot(None))
            from sqlalchemy import func

            stmt = stmt.filter(func.lower(Product.brand).in_(lowered))
        if category_id is not None:
            stmt = stmt.filter(Product.category_id == category_id)
        candidates = stmt.order_by(Product.sales.desc()).limit(200).all()

        if not candidates:
            return {"items": [], "strategy": "structured", "query": query, "total": 0}

        scored: list[tuple[float, Product, list[str]]] = []
        for product in candidates:
            haystack = " ".join(
                filter(
                    None,
                    [
                        product.title or "",
                        product.subtitle or "",
                        product.brand or "",
                        product.search_text or "",
                        product.description or "",
                    ],
                )
            ).lower()
            hits = [term for term in terms if term in haystack]
            keyword_score = len(hits) / max(len(terms), 1) if terms else 0.0
            rating_score = min(float(product.rating or 0) / 5.0, 1.0) * 0.35
            sales_score = min(math.log1p(product.sales or 0) / 12.0, 0.3)
            price_bonus = 0.05 if (max_price is not None and float(product.price) <= max_price) else 0.0
            total = keyword_score * 0.6 + rating_score + sales_score + price_bonus
            scored.append((round(min(total, 1.0), 4), product, hits))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[:top_k]
        if terms and all(not hits for _, _, hits in top):
            # 关键词完全没命中时退回"热销优先"，保证导购场景永远有结果
            top = sorted(scored, key=lambda item: (item[1].sales or 0), reverse=True)[:top_k]

        categories = _category_names(db, {p.category_id for _, p, _ in top})
        items = []
        for score, product, hits in top:
            items.append(
                {
                    "sku": product.sku,
                    "title": product.title,
                    "brand": product.brand,
                    "price": round(float(product.price or 0), 2),
                    "originalPrice": round(float(product.original_price), 2)
                    if product.original_price
                    else None,
                    "rating": round(float(product.rating or 0), 1),
                    "sales": product.sales,
                    "stock": product.stock,
                    "categoryName": categories.get(product.category_id),
                    "score": score,
                    "reason": (
                        f"命中关键词：{'/'.join(hits[:3])}" if hits else "热销与高评分综合推荐"
                    ),
                    "imageUrl": product.image_url,
                }
            )
        return {
            "items": items,
            "strategy": "hybrid" if terms else "structured",
            "query": query,
            "total": len(items),
        }


def get_product_detail(ctx: ToolContext, sku: str) -> dict[str, Any]:
    """按 SKU 取商品详情（含 description）。"""
    with session_scope() as db:
        product = db.query(Product).filter(Product.sku == sku.upper()).one_or_none()
        if product is None:
            product = db.query(Product).filter(Product.sku == sku).one_or_none()
        if product is None:
            return {"found": False, "sku": sku, "message": f"未找到 SKU 为 {sku} 的商品"}
        categories = _category_names(db, {product.category_id})
        data = product_to_dict(product, categories.get(product.category_id))
        return {"found": True, "product": data, "summary": f"{data['title']} ¥{data['price']}"}


def compare_products(ctx: ToolContext, skus: list[str]) -> dict[str, Any]:
    """横向对比：价格、评分、库存、核心属性差异。"""
    normalized = [s.upper() for s in skus]
    with session_scope() as db:
        products = db.query(Product).filter(Product.sku.in_(normalized)).all()
        by_sku = {p.sku: p for p in products}
        items: list[dict[str, Any]] = []
        for sku in normalized:
            product = by_sku.get(sku)
            if product is None:
                items.append({"sku": sku, "missing": True})
                continue
            items.append(
                {
                    "sku": product.sku,
                    "title": product.title,
                    "brand": product.brand,
                    "price": round(float(product.price or 0), 2),
                    "rating": round(float(product.rating or 0), 1),
                    "sales": product.sales,
                    "stock": product.stock,
                    "attrs": product.attrs or {},
                    "highlight": _highlight(product),
                }
            )
        available = [item for item in items if not item.get("missing")]
        cheapest = min(available, key=lambda item: item["price"])["sku"] if available else None
        best_rated = max(available, key=lambda item: item["rating"])["sku"] if available else None
        return {
            "items": items,
            "cheapest": cheapest,
            "bestRated": best_rated,
            "verdict": _verdict(available),
        }


def _highlight(product: Product) -> str:
    attrs = product.attrs or {}
    parts = [f"{key}={value}" for key, value in list(attrs.items())[:3]]
    return "、".join(parts) if parts else (product.subtitle or "无额外参数")


def _verdict(items: list[dict[str, Any]]) -> str:
    if not items:
        return "没有可对比的有效商品"
    cheapest = min(items, key=lambda item: item["price"])
    return (
        f"预算优先选 {cheapest['sku']}（¥{cheapest['price']}）；"
        f"综合体验优先可考虑评分更高的型号。"
    )


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
SEARCH_PRODUCTS = ToolSpec(
    name="search_products",
    description="按自然语言需求搜索商品，支持价格区间、品牌、类目过滤，返回带推荐理由的结果。",
    func=search_products,
    risk=Risk.READ,
    args_model=SearchProductsArgs,
    timeout_seconds=10,
    max_retries=1,
    summarize=lambda data: f"命中 {len(data.get('items', []))} 件商品"
    + (f"，最低价 ¥{min(i['price'] for i in data['items'])}" if data.get("items") else ""),
)

GET_PRODUCT_DETAIL = ToolSpec(
    name="get_product_detail",
    description="根据 SKU 获取商品完整详情（价格、库存、属性、描述）。",
    func=get_product_detail,
    risk=Risk.READ,
    args_model=ProductDetailArgs,
    timeout_seconds=8,
    max_retries=1,
    summarize=lambda data: data.get("summary") or data.get("message", ""),
)

COMPARE_PRODUCTS = ToolSpec(
    name="compare_products",
    description="对比 2~4 款商品的价格、评分、销量与核心属性，给出选购结论。",
    func=compare_products,
    risk=Risk.READ,
    args_model=CompareProductsArgs,
    timeout_seconds=10,
    max_retries=0,
    summarize=lambda data: f"已对比 {len([i for i in data.get('items', []) if not i.get('missing')])} 款商品",
)

__all__ = [
    "COMPARE_PRODUCTS",
    "GET_PRODUCT_DETAIL",
    "SEARCH_PRODUCTS",
    "compare_products",
    "get_product_detail",
    "product_to_dict",
    "search_products",
]
