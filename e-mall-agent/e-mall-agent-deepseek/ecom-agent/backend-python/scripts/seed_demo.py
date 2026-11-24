#!/usr/bin/env python
"""演示数据灌入：用户 / 商品 / 订单 / 物流 / 知识文档，并调用 ``app.rag.ingest`` 建索引。

零外部依赖用法（SQLite + 内存向量库）::

    DATABASE_URL=sqlite:///./var/demo.db VECTOR_STORE=memory python scripts/seed_demo.py

MySQL 用法（需先用 ``deploy/mysql/init`` 建库表）::

    python scripts/seed_demo.py --database-url "mysql+pymysql://ecom:ecom123@127.0.0.1:3306/ecom_agent?charset=utf8mb4"

特性：

* **幂等**：用户/商品/订单按唯一键 upsert，知识文档按标题复用；
  ``--force-reindex`` 强制重建索引，普通执行会把已索引文档标记为 skipped；
* **可复现**：订单时间相对当前时间偏移，退款资格（7 天窗口/金额阈值）始终可演示；
* **离线**：不配置 ``DASHSCOPE_API_KEY`` 时 embedding 自动降级 hash；
  ``VECTOR_STORE=memory`` 时不依赖 Milvus。

退出码：0 成功；1 失败（数据库不可达、建表失败等）。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：#!/usr/bin/env python 演示数据灌入：用户 / 商品 / 订单 / 物流 / 知识文档，并调用 ``
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEMO_PASSWORD = "Passw0rd!"

USERS: list[dict[str, str]] = [
    {"username": "demo", "display_name": "演示用户", "email": "demo@example.com", "roles": "USER"},
    {"username": "agent", "display_name": "客服小星", "email": "agent@example.com", "roles": "AGENT,USER"},
    {"username": "admin", "display_name": "运营管理员", "email": "admin@example.com", "roles": "ADMIN,USER"},
]

CATEGORIES: list[tuple[str, int, int]] = [
    ("手机数码", 0, 1),
    ("电脑办公", 0, 2),
    ("耳机音频", 0, 3),
    ("智能穿戴", 0, 4),
]

# category 为 CATEGORIES 的下标 + 1（与 schema 中的 category.id 对应）
PRODUCTS: list[dict[str, object]] = [
    {
        "sku": "SKU-1001",
        "title": "小米 14 12+256G 徕卡光学镜头",
        "subtitle": "骁龙 8 Gen3 / 徕卡三摄 / 90W 快充",
        "brand": "小米",
        "category": 1,
        "price": 2999,
        "original_price": 3999,
        "stock": 120,
        "rating": 4.8,
        "sales": 8600,
        "attrs": {"影像": "徕卡三摄", "芯片": "骁龙 8 Gen3", "重量": "193g"},
        "description": "小屏旗舰，徕卡影像调校，适合拍照与日常使用。",
    },
    {
        "sku": "SKU-1002",
        "title": "Redmi K70 12+256G",
        "subtitle": "2K 屏 / 5500mAh / 120W 快充",
        "brand": "小米",
        "category": 1,
        "price": 2499,
        "original_price": 2999,
        "stock": 200,
        "rating": 4.7,
        "sales": 12000,
        "attrs": {"续航": "5500mAh", "快充": "120W", "屏幕": "2K 直屏"},
        "description": "性能与续航均衡，性价比高。",
    },
    {
        "sku": "PH-003",
        "title": "iPhone 16 128G",
        "subtitle": "A18 芯片 / iOS 生态 / 4800 万主摄",
        "brand": "Apple",
        "category": 1,
        "price": 5999,
        "original_price": 5999,
        "stock": 60,
        "rating": 4.9,
        "sales": 5200,
        "attrs": {"系统": "iOS", "芯片": "A18", "影像": "4800 万像素"},
        "description": "生态完善、系统更新周期长。",
    },
    {
        "sku": "PH-004",
        "title": "小米 15 12+256G",
        "subtitle": "徕卡影像 / 骁龙 8 Elite / 90W 快充",
        "brand": "小米",
        "category": 1,
        "price": 4499,
        "original_price": 4999,
        "stock": 80,
        "rating": 4.8,
        "sales": 4300,
        "attrs": {"影像": "徕卡", "快充": "90W", "屏幕": "1.5K 高刷"},
        "description": "小尺寸旗舰，拍照与手感兼顾。",
    },
    {
        "sku": "PC-001",
        "title": "联想小新 Pro 16",
        "subtitle": "锐龙 7 8845H / 32G / 1T / 2.5K 120Hz",
        "brand": "联想",
        "category": 2,
        "price": 5799,
        "original_price": 6299,
        "stock": 32,
        "rating": 4.7,
        "sales": 2100,
        "attrs": {"屏幕": "2.5K 120Hz", "重量": "1.9kg", "内存": "32G"},
        "description": "大屏高性能轻薄本，适合办公与轻度剪辑。",
    },
    {
        "sku": "PC-002",
        "title": "华为 MateBook 14",
        "subtitle": "2.8K OLED / 1.31kg / 酷睿 Ultra",
        "brand": "华为",
        "category": 2,
        "price": 6999,
        "original_price": 7499,
        "stock": 18,
        "rating": 4.6,
        "sales": 1500,
        "attrs": {"重量": "1.31kg", "屏幕": "2.8K OLED", "生态": "多屏协同"},
        "description": "极致轻薄，适合通勤与移动办公。",
    },
    {
        "sku": "AU-001",
        "title": "Redmi Buds 6 Pro 真无线降噪耳机",
        "subtitle": "55dB 主动降噪 / 38 小时续航",
        "brand": "小米",
        "category": 3,
        "price": 399,
        "original_price": 499,
        "stock": 300,
        "rating": 4.6,
        "sales": 9800,
        "attrs": {"降噪": "55dB", "续航": "38 小时", "佩戴": "入耳式"},
        "description": "通勤降噪首选，性价比高。",
    },
    {
        "sku": "AU-002",
        "title": "索尼 WH-1000XM5 头戴降噪耳机",
        "subtitle": "双芯片降噪 / 30 小时续航 / 轻量佩戴",
        "brand": "索尼",
        "category": 3,
        "price": 2499,
        "original_price": 2999,
        "stock": 45,
        "rating": 4.8,
        "sales": 2600,
        "attrs": {"降噪": "双芯片", "续航": "30 小时", "类型": "头戴式"},
        "description": "中低频降噪出色，适合长途通勤。",
    },
    {
        "sku": "KB-001",
        "title": "雷柏 V500Pro 机械键盘",
        "subtitle": "青轴 / 有线 / 混光背光",
        "brand": "雷柏",
        "category": 2,
        "price": 249,
        "original_price": 299,
        "stock": 150,
        "rating": 4.5,
        "sales": 7600,
        "attrs": {"轴体": "青轴", "连接": "有线"},
        "description": "入门机械键盘，段落感强。",
    },
    {
        "sku": "KB-002",
        "title": "罗技 K380 无线键盘",
        "subtitle": "蓝牙多设备 / 轻薄便携",
        "brand": "罗技",
        "category": 2,
        "price": 199,
        "original_price": 229,
        "stock": 220,
        "rating": 4.4,
        "sales": 11000,
        "attrs": {"连接": "蓝牙", "重量": "423g", "类型": "薄膜"},
        "description": "轻办公与出差备用键盘。",
    },
]

# 订单以 demo 用户为 owner；时间相对 now 偏移，保证退款资格可演示
ORDERS: list[dict[str, object]] = [
    {
        "order_no": "SO202611230001",
        "status": "SHIPPED",
        "sku": "SKU-1001",
        "quantity": 1,
        "days_ago": 3,
        "shipped_days_ago": 2,
        "logistics": {
            "company": "顺丰速运",
            "tracking_no": "SF1234567890",
            "status": "IN_TRANSIT",
            "latest_event": "快件已到达杭州转运中心",
            "events": [
                {"time": "2026-11-22 09:20", "desc": "商家已发货，顺丰速运已揽收"},
                {"time": "2026-11-22 18:05", "desc": "快件已到达杭州转运中心"},
            ],
        },
    },
    {
        "order_no": "SO202611230002",
        "status": "DELIVERED",
        "sku": "SKU-1002",
        "quantity": 1,
        "days_ago": 5,
        "shipped_days_ago": 4,
        "finished_days_ago": 2,
        "logistics": {
            "company": "京东物流",
            "tracking_no": "JD9876543210",
            "status": "SIGNED",
            "latest_event": "已签收，签收人：本人",
            "events": [{"time": "2026-11-22 14:30", "desc": "已签收，签收人：本人"}],
        },
    },
    {
        "order_no": "SO202611230003",
        "status": "FINISHED",
        "sku": "PH-003",
        "quantity": 1,
        "days_ago": 15,
        "shipped_days_ago": 14,
        "finished_days_ago": 10,
    },
    {
        "order_no": "SO202611230004",
        "status": "PAID",
        "sku": "PC-002",
        "quantity": 2,
        "days_ago": 1,
    },
]

# 知识文档：覆盖退款/运费/时效/保修/价保/会员/发票/以旧换新（对应 eval_data/rag.jsonl）
KNOWLEDGE_DOCS: list[dict[str, str]] = [
    {
        "title": "退款与退货运费政策",
        "doc_type": "POLICY",
        "text": """一、适用范围
本政策适用于星图商城自营及平台商家销售的可退商品，自用户签收之日起计算。

二、七天无理由退货
1. 自签收之日起 7 天内，商品不影响二次销售、配件与包装齐全的，可申请七天无理由退货。
2. 无理由退货的退货运费由买家承担；商品存在质量问题或发错货的，运费由商家承担。
3. 生鲜、定制、虚拟商品及已拆封的个人护理用品不支持七天无理由退货；存在质量问题的仍可申请退款或补发，需在签收后 24 小时内提交照片。

三、退款时效
商家审核通过后 1-3 个工作日内原路退回；银行或支付渠道清算时间另计，通常不超过 24 小时。超时未到账可转人工核查退款单状态。

四、退款失败
常见原因：原支付渠道已失效、退款单与支付流水不匹配、订单存在争议处理中。此类情况需人工核实后重新发起。""",
    },
    {
        "title": "以旧换新服务规则",
        "doc_type": "POLICY",
        "text": """一、支持品类
手机、平板、笔记本、耳机、智能穿戴支持以旧换新；旧机需可正常开机、无严重进液与变形。

二、补贴规则
补贴金额以回收检测结果为准，耳机类目最高补贴 300 元，手机类目最高补贴 1500 元。检测结果会在 24 小时内同步到订单页。

三、操作路径
下单时在结算页勾选「以旧换新」，选择回收方式（上门/寄回），旧机质检通过后补贴直接抵扣新机价款。

四、注意事项
以旧换新订单不支持与其他优惠券叠加；回收完成后旧机不可退回。""",
    },
    {
        "title": "售后服务手册",
        "doc_type": "MANUAL",
        "text": """一、保修范围
保修期内维修需提供订单号或发票、产品序列号、故障描述与照片。人为损坏、进液、私自拆修不在保修范围内；符合条件的维修免工时费与配件费。

二、发票
订单完成后可在「订单详情 → 申请开票」提交，支持电子普通发票与增值税专用发票；专票需提供公司名称、税号与开户信息，电子发票一般 1 个工作日内开具。发票丢失仍可凭订单号与序列号保修。

三、价保规则
自签收之日起 7 天内，同一商品在同一平台出现降价可申请价保，退还差价；秒杀、优惠券、赠品与会员专享价不参与价保，申请入口在订单详情的「价格保护」。

四、会员权益
普通会员享基础售后；银卡会员享生日券与运费券；金卡会员额外享专属客服、优先发货与每月 2 次免运费退货。等级按近 12 个月消费与活跃度综合评定。""",
    },
    {
        "title": "退换货与发票常见问题",
        "doc_type": "FAQ",
        "text": """Q1：定制商品可以退吗？
定制类商品（刻字、改尺寸、定制图案等）不支持七天无理由退货；定制内容与约定不符或存在质量问题的，可申请重做或退款，需提供对比照片与约定凭证。

Q2：超过 7 天还能退吗？
超过 7 天不支持无理由退货；存在质量问题的可按保修政策申请维修或退换。

Q3：退款多久到账？
审核通过后 1-3 个工作日原路退回。

Q4：如何联系人工客服？
人工客服工作时间每天 9:00-21:00，可在对话中回复「转人工」，或在「我的 → 客服中心」提交工单；商品安全问题会优先接入。""",
    },
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _hash_password(plain: str) -> str:
    """优先复用安全模块的 BCrypt；依赖不可用时直接用 bcrypt，仍不可用才退化为占位哈希。"""
    try:
        from app.security.auth import hash_password

        return hash_password(plain)
    except Exception:  # noqa: BLE001 - auth 模块可能因循环导入/缺 passlib 不可用
        pass
    try:
        import bcrypt

        return bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")
    except Exception:  # noqa: BLE001 - 离线环境无 bcrypt 时只用于数据展示
        return "$demo$" + hashlib.sha256(plain.encode("utf-8")).hexdigest()[:40]


def _now():
    from app.common.timeutil import utcnow

    return utcnow()


def _search_text(product: dict[str, object]) -> str:
    attrs = product.get("attrs") or {}
    values = list(attrs.values()) if isinstance(attrs, dict) else []
    parts = [
        str(product.get("title") or ""),
        str(product.get("subtitle") or ""),
        str(product.get("brand") or ""),
        str(product.get("description") or ""),
        *[str(value) for value in values],
        "以旧换新 价保 发票 保修",
    ]
    return " ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# 各实体
# ---------------------------------------------------------------------------
def seed_users() -> tuple[dict[str, int], int]:
    """灌用户 + 画像，返回 ``{username: id}`` 与新建数量。"""
    from app.infra.db import session_scope
    from app.infra.models import SysUser, UserProfile

    ids: dict[str, int] = {}
    created = 0
    password_hash = _hash_password(DEMO_PASSWORD)
    with session_scope() as db:
        for spec in USERS:
            user = db.query(SysUser).filter(SysUser.username == spec["username"]).one_or_none()
            if user is None:
                user = SysUser(
                    username=spec["username"],
                    password_hash=password_hash,
                    display_name=spec["display_name"],
                    email=spec["email"],
                    roles=spec["roles"],
                    status=1,
                )
                db.add(user)
                db.flush()
                created += 1
            else:
                user.display_name = spec["display_name"]
                user.email = spec["email"]
                user.roles = spec["roles"]
                user.status = 1
            ids[spec["username"]] = int(user.id)

            profile = db.get(UserProfile, int(user.id))
            if profile is None:
                db.add(
                    UserProfile(
                        user_id=int(user.id),
                        nickname=spec["display_name"],
                        phone="13800008888",
                        member_level="GOLD" if spec["username"] == "demo" else "NORMAL",
                        preferred_brands=["小米", "Apple"],
                        budget_min=1000,
                        budget_max=8000,
                        sizes={"shoe": 42, "clothes": "L"},
                    )
                )
        db.flush()
    return ids, created


def seed_products() -> int:
    """灌类目与商品（按 SKU upsert），返回新建商品数。"""
    from app.infra.db import session_scope
    from app.infra.models import Category, Product

    created = 0
    with session_scope() as db:
        category_ids: dict[int, int] = {}
        for name, parent_id, sort in CATEGORIES:
            row = db.query(Category).filter(Category.name == name).one_or_none()
            if row is None:
                row = Category(name=name, parent_id=parent_id, sort=sort)
                db.add(row)
                db.flush()
            category_ids[sort] = int(row.id)
        db.flush()

        for spec in PRODUCTS:
            sku = str(spec["sku"])
            row = db.query(Product).filter(Product.sku == sku).one_or_none()
            payload = {
                "title": str(spec["title"]),
                "subtitle": str(spec.get("subtitle") or ""),
                "brand": str(spec.get("brand") or ""),
                "category_id": category_ids.get(int(spec["category"]), 0),
                "price": float(spec["price"]),
                "original_price": float(spec.get("original_price") or spec["price"]),
                "stock": int(spec.get("stock") or 0),
                "status": 1,
                "rating": float(spec.get("rating") or 5.0),
                "sales": int(spec.get("sales") or 0),
                "image_url": f"https://cdn.example.com/products/{sku}.jpg",
                "attrs": spec.get("attrs") or {},
                "description": str(spec.get("description") or ""),
                "search_text": _search_text(spec),
            }
            if row is None:
                db.add(Product(sku=sku, **payload))
                created += 1
            else:
                for key, value in payload.items():
                    setattr(row, key, value)
    return created


def seed_orders(user_id: int) -> int:
    """灌订单/明细/物流（按订单号 upsert），返回新建订单数。"""
    from app.infra.db import session_scope
    from app.infra.models import Logistics, OrderInfo, OrderItem, Product

    created = 0
    now = _now()
    with session_scope() as db:
        for spec in ORDERS:
            order_no = str(spec["order_no"])
            product = db.query(Product).filter(Product.sku == str(spec["sku"])).one_or_none()
            price = float(product.price) if product is not None else 0.0
            quantity = int(spec.get("quantity") or 1)
            total = round(price * quantity, 2)
            created_at = now - timedelta(days=int(spec["days_ago"]))
            paid_at = created_at + timedelta(minutes=5)
            shipped_at = (
                now - timedelta(days=int(spec["shipped_days_ago"]))
                if spec.get("shipped_days_ago") is not None
                else None
            )
            finished_at = (
                now - timedelta(days=int(spec["finished_days_ago"]))
                if spec.get("finished_days_ago") is not None
                else None
            )

            order = db.query(OrderInfo).filter(OrderInfo.order_no == order_no).one_or_none()
            if order is None:
                order = OrderInfo(order_no=order_no, user_id=user_id)
                db.add(order)
                created += 1
            order.user_id = user_id
            order.status = str(spec["status"])
            order.total_amount = total
            order.pay_amount = total
            order.receiver_name = "张伟"
            order.receiver_phone = "13800008888"
            order.receiver_address = "浙江省杭州市西湖区文三路 100 号 3 幢 501 室"
            order.created_at = created_at
            order.paid_at = paid_at
            order.shipped_at = shipped_at
            order.finished_at = finished_at
            db.flush()

            items = db.query(OrderItem).filter(OrderItem.order_id == int(order.id)).all()
            if not items:
                db.add(
                    OrderItem(
                        order_id=int(order.id),
                        product_id=int(product.id) if product is not None else 0,
                        sku=str(spec["sku"]),
                        title=str(product.title) if product is not None else str(spec["sku"]),
                        price=price,
                        quantity=quantity,
                    )
                )

            logistics_spec = spec.get("logistics")
            if isinstance(logistics_spec, dict):
                logistics = (
                    db.query(Logistics).filter(Logistics.order_id == int(order.id)).one_or_none()
                )
                if logistics is None:
                    logistics = Logistics(order_id=int(order.id), order_no=order_no)
                    db.add(logistics)
                logistics.order_no = order_no
                logistics.company = str(logistics_spec.get("company") or "")
                logistics.tracking_no = str(logistics_spec.get("tracking_no") or "")
                logistics.status = str(logistics_spec.get("status") or "PENDING")
                logistics.latest_event = str(logistics_spec.get("latest_event") or "")
                logistics.events = list(logistics_spec.get("events") or [])
                logistics.updated_at = now
    return created


def seed_knowledge(*, force: bool = False) -> list[dict[str, object]]:
    """灌知识文档并建索引（按标题幂等）。"""
    from app.infra.db import session_scope
    from app.infra.models import KnowledgeDocument
    from app.rag.ingest import ingest_text, reindex_document

    results: list[dict[str, object]] = []
    for doc in KNOWLEDGE_DOCS:
        title = doc["title"]
        with session_scope() as db:
            row = (
                db.query(KnowledgeDocument)
                .filter(
                    KnowledgeDocument.title == title,
                    KnowledgeDocument.deleted_at.is_(None),
                )
                .first()
            )
            existing = (
                (int(row.id), str(row.status), int(row.chunk_count or 0)) if row is not None else None
            )
        if existing is None:
            result = ingest_text(title, doc["text"], doc_type=doc["doc_type"])
        elif force or existing[1] != "READY":
            result = reindex_document(existing[0])
        else:
            result = {
                "ok": True,
                "skipped": True,
                "documentId": existing[0],
                "chunkCount": existing[2],
                "reason": "已索引，使用 --force-reindex 可重建",
            }
        results.append({"title": title, "docType": doc["doc_type"], **result})
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="灌入星图商城演示数据")
    parser.add_argument("--database-url", default=None, help="覆盖 DATABASE_URL（优先级最高）")
    parser.add_argument(
        "--vector-store",
        default=None,
        choices=["auto", "memory", "milvus"],
        help="覆盖 VECTOR_STORE（本地演示建议 memory）",
    )
    parser.add_argument("--force-reindex", action="store_true", help="强制重建知识索引")
    parser.add_argument("--skip-knowledge", action="store_true", help="只灌业务数据，不建索引")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出摘要")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    if args.vector_store:
        os.environ["VECTOR_STORE"] = args.vector_store
    os.environ.setdefault("AUTO_CREATE_TABLES", "true")

    try:
        from app.config import settings
        from app.infra.db import init_db, ping
    except Exception as exc:  # noqa: BLE001 - 依赖缺失时给出可读提示
        print(f"初始化失败（检查依赖与环境变量）: {exc}", file=sys.stderr)
        return 1

    if not args.json:
        print(f"[env] DATABASE_URL={settings.database_uri}")
        print(f"[env] VECTOR_STORE={settings.vector_store}  EMBEDDING={settings.embedding_provider}")
        if settings.mock_llm:
            print("[env] MOCK_LLM=true（无需任何 API Key）")

    try:
        init_db(create_tables=True)
        if not ping():
            print("数据库不可达：请检查 DATABASE_URL / MYSQL_* 配置", file=sys.stderr)
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"建表/探活失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    summary: dict[str, object] = {"database": settings.database_uri.split("@")[-1]}
    knowledge_docs: list[dict[str, object]] = []
    knowledge_error: str | None = None
    try:
        users, users_created = seed_users()
        products_created = seed_products()
        demo_user_id = users.get("demo", 0)
        orders_created = seed_orders(demo_user_id)
    except Exception as exc:  # noqa: BLE001
        print(f"业务数据灌入失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    summary["users"] = {"ids": users, "created": users_created, "password": DEMO_PASSWORD}
    summary["products"] = {"created": products_created, "total": len(PRODUCTS)}
    summary["orders"] = {"created": orders_created, "total": len(ORDERS)}

    if args.skip_knowledge:
        summary["knowledge"] = {"skipped": True, "reason": "--skip-knowledge"}
    else:
        try:
            knowledge_docs = seed_knowledge(force=args.force_reindex)
            summary["knowledge"] = {"documents": knowledge_docs}
        except Exception as exc:  # noqa: BLE001 - 业务数据已成功，索引失败给出告警
            knowledge_error = f"{type(exc).__name__}: {exc}"
            summary["knowledge"] = {"error": knowledge_error}
            print(f"[warn] 知识索引失败（业务数据已灌入）: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print()
    print(f"用户: {len(USERS)}（demo={users.get('demo')}，口令 {DEMO_PASSWORD}）")
    print(f"商品: {len(PRODUCTS)} 件（新建 {products_created}）")
    print(f"订单: {len(ORDERS)} 笔（新建 {orders_created}）")
    for item in knowledge_docs:
        state = "skipped" if item.get("skipped") else ("ok" if item.get("ok") else "failed")
        print(
            f"知识文档《{item.get('title')}》: {state}"
            f" chunks={item.get('chunkCount', 0)} docId={item.get('documentId')}"
        )
    if knowledge_error:
        print(f"知识索引错误: {knowledge_error}", file=sys.stderr)
    print("\n完成。可用 GET /mcp/tools 查看工具清单，或 scripts/run_eval.py 跑评测。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
