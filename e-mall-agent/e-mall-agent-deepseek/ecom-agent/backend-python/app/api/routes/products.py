"""商品接口：列表、详情、语义检索。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议
# 职责：商品接口：列表、详情、语义检索
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_db
from app.common.envelope import ok, page_result
from app.common.errors import not_found
from app.common.tracecontext import get_trace_id
from app.infra.models import Category, Product

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["商品"])


class ProductSearchReq(BaseModel):
    """语义检索请求。"""

    query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=5, ge=1, le=20, alias="topK")
    max_price: float | None = Field(default=None, alias="maxPrice")
    min_price: float | None = Field(default=None, alias="minPrice")
    brands: list[str] | None = None

    model_config = {"populate_by_name": True}


def to_vo(row: Product, category_name: str | None = None) -> dict[str, Any]:
    """商品对外结构（docs/03 ProductVO）。"""
    return {
        "id": row.id,
        "sku": row.sku,
        "title": row.title,
        "subtitle": row.subtitle,
        "brand": row.brand,
        "categoryId": row.category_id,
        "categoryName": category_name,
        "price": float(row.price),
        "originalPrice": float(row.original_price) if row.original_price is not None else None,
        "stock": row.stock,
        "rating": float(row.rating) if row.rating is not None else None,
        "sales": row.sales,
        "imageUrl": row.image_url,
        "attrs": row.attrs or {},
        "status": row.status,
        "description": row.description,
    }


@router.get("", summary="商品列表")
def list_products(
    keyword: str | None = Query(default=None, max_length=100),
    category_id: int | None = Query(default=None, alias="categoryId"),
    min_price: float | None = Query(default=None, alias="minPrice", ge=0),
    max_price: float | None = Query(default=None, alias="maxPrice", ge=0),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """条件过滤 + 分页，按销量倒序。"""
    query = db.query(Product).filter(Product.status == 1)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Product.title.like(like),
                Product.subtitle.like(like),
                Product.brand.like(like),
                Product.search_text.like(like),
            )
        )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    total = query.count()
    rows = (
        query.order_by(Product.sales.desc(), Product.id.asc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    names = _category_names(db)
    items = [to_vo(row, names.get(row.category_id)) for row in rows]
    return ok(page_result(items, total, page, size))


@router.get("/{sku}", summary="商品详情")
def get_product(
    sku: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    row = db.query(Product).filter(Product.sku == sku).one_or_none()
    if row is None:
        raise not_found(f"商品不存在: {sku}")
    return ok(to_vo(row, _category_names(db).get(row.category_id)))


@router.post("/search", summary="语义检索（向量 + 结构化过滤）")
def search(req: ProductSearchReq, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """先用向量召回，再按价格/品牌过滤；向量不可用时降级关键词。

    返回体里的 ``strategy`` 明确告知本次走的哪条路（前端会展示，便于排查）。
    """
    candidate_ids, strategy = _vector_candidates(req.query, req.top_k * 4)

    if candidate_ids:
        rows = db.query(Product).filter(Product.id.in_(candidate_ids), Product.status == 1).all()
        by_id = {row.id: row for row in rows}
        ordered = [by_id[i] for i in candidate_ids if i in by_id]
    else:
        strategy = "keyword"
        like = f"%{req.query.strip()}%"
        ordered = (
            db.query(Product)
            .filter(
                Product.status == 1,
                or_(Product.title.like(like), Product.subtitle.like(like), Product.brand.like(like)),
            )
            .order_by(Product.sales.desc())
            .limit(req.top_k * 4)
            .all()
        )

    filtered = [row for row in ordered if _accepts(row, req)]
    items = [
        {
            "sku": row.sku,
            "title": row.title,
            "price": float(row.price),
            "score": round(1.0 - index * 0.05, 4),
            "reason": (row.subtitle or row.brand or "")[:60],
        }
        for index, row in enumerate(filtered[: req.top_k])
    ]
    return ok({"items": items, "strategy": strategy})


def _accepts(row: Product, req: ProductSearchReq) -> bool:
    price = float(row.price)
    if req.min_price is not None and price < req.min_price:
        return False
    if req.max_price is not None and price > req.max_price:
        return False
    if req.brands and (row.brand or "") not in req.brands:
        return False
    return True


def _vector_candidates(query: str, limit: int) -> tuple[list[int], str]:
    """向量召回商品 id；失败返回 ``([], "vector_unavailable")``。"""
    try:
        from app.rag.embedding import get_embedding
        from app.rag.store import get_store

        store = get_store()
        vector = get_embedding().embed_query(query)
        hits = store.search_dense("product", vector, top_k=limit)
        ids = [int(hit.id) for hit in hits]
        return ids, "hybrid" if ids else "keyword"
    except Exception as exc:  # noqa: BLE001 - 未部署 Milvus 属常态
        logger.debug("商品向量召回不可用 trace=%s err=%s", get_trace_id(), exc)
        return [], "vector_unavailable"


def _category_names(db: Session) -> dict[int, str]:
    try:
        return {int(row.id): row.name for row in db.query(Category).all()}
    except Exception:  # noqa: BLE001
        return {}


__all__ = ["router", "to_vo"]
