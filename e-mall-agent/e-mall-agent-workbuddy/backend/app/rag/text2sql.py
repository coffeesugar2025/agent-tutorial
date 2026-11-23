"""Text2SQL / Text2Cypher（RAG 进阶层）。

- ``Text2SQL``：在 SQLite 内存库上建电商模拟表，把自然语言转成受限 SELECT，
  经白名单校验后执行；禁止 DML/DDL、多语句与注释注入，自动补 LIMIT。
- ``Text2Cypher``：接口骨架 + 确定性模板，只产出 Cypher 字符串与参数（不执行），
  便于后续接入真实 Neo4j。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 白名单与模拟数据
# ---------------------------------------------------------------------------
ALLOWED_TABLES: dict[str, tuple[str, ...]] = {
    "products": ("id", "name", "category", "price", "stock", "tags", "description"),
    "orders": ("id", "customer_id", "total", "status", "created_at", "address"),
    "order_items": ("order_id", "product_id", "quantity", "unit_price"),
}
ALL_COLUMNS = {column for columns in ALLOWED_TABLES.values() for column in columns}

_SEED_PRODUCTS = [
    ("P001", "无线降噪耳机 Pro", "数码", 899.0, 12, "降噪,蓝牙5.3", "40小时续航，主动降噪"),
    ("P002", "人体工学椅", "家具", 1299.0, 7, "网布,腰托", "透气网布，腰托可调"),
    ("P003", "机械键盘", "数码", 459.0, 30, "键盘,办公", "青轴机械键盘"),
    ("P004", "实木书桌", "家具", 899.0, 4, "实木,办公", "1.2米实木书桌"),
    ("P005", "便携咖啡机", "家居", 329.0, 18, "咖啡,便携", "随行浓缩咖啡机"),
    ("P006", "跑步鞋", "服装", 599.0, 2, "运动,鞋", "轻量缓震跑鞋"),
    ("P007", "智能台灯", "家居", 259.0, 25, "照明,办公", "无级调光护眼台灯"),
    ("P008", "双肩背包", "服装", 399.0, 15, "通勤,背包", "15寸电脑仓"),
]
_SEED_ORDERS = [
    ("O1001", "U001", 1358.0, "paid", "2026-01-05T09:00:00+00:00", "北京市朝阳区"),
    ("O1002", "U002", 888.0, "created", "2026-01-06T10:30:00+00:00", "上海市浦东新区"),
    ("O1003", "U001", 329.0, "shipped", "2026-01-07T12:00:00+00:00", "深圳市南山区"),
]
_SEED_ITEMS = [
    ("O1001", "P001", 1, 899.0),
    ("O1001", "P002", 1, 459.0),
    ("O1002", "P003", 1, 459.0),
    ("O1002", "P007", 1, 259.0),
    ("O1003", "P005", 1, 329.0),
]

# 命中即拒绝：DML / DDL / 注入常用关键字
_BANNED_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|pragma|"
    r"attach|detach|vacuum|union|into|outfile|load_extension|execute|"
    r"grant|revoke|shell|trigger|index|view)\b", re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)
_STRING_RE = re.compile(r"'(?:''|[^'])*'")


def create_demo_db() -> sqlite3.Connection:
    """创建并填充 SQLite 内存电商库。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE products (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
            price REAL NOT NULL, stock INTEGER NOT NULL, tags TEXT, description TEXT
        );
        CREATE TABLE orders (
            id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, total REAL NOT NULL,
            status TEXT NOT NULL, created_at TEXT, address TEXT
        );
        CREATE TABLE order_items (
            order_id TEXT NOT NULL, product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL, unit_price REAL NOT NULL
        );
        """
    )
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", _SEED_PRODUCTS)
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", _SEED_ORDERS)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?)", _SEED_ITEMS)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 结果结构
# ---------------------------------------------------------------------------
@dataclass
class SQLResult:
    sql: str
    params: tuple[Any, ...]
    columns: list[str]
    rows: list[tuple[Any, ...]]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]


@dataclass
class CypherQuery:
    cypher: str
    params: dict[str, Any] = field(default_factory=dict)
    pattern: str = ""


# ---------------------------------------------------------------------------
# SQL 校验
# ---------------------------------------------------------------------------
def _strip_strings(sql: str) -> str:
    """把字符串字面量替换成 ''，避免关键字出现在值里造成误判/漏判。"""
    return _STRING_RE.sub("''", sql)


def _projection_columns(sql: str) -> list[str]:
    """取 SELECT 投影中的裸列名，常量/聚合只取内部列名。"""
    head = re.split(r"\bfrom\b", sql, maxsplit=1, flags=re.IGNORECASE)[0]
    expression = re.sub(r"^\s*select\s+", "", head, flags=re.IGNORECASE)
    expression = re.sub(r"^\s*distinct\s+", "", expression, flags=re.IGNORECASE)
    columns: list[str] = []
    for part in expression.split(","):
        part = re.split(r"\s+as\s+", part.strip(), maxsplit=1, flags=re.IGNORECASE)[0]
        part = part.strip()
        aggregate = re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*\((.*)\)$", part)
        if aggregate:
            part = aggregate.group(1).strip()
        if part == "*" or not part:
            continue
        columns.append(part.split(".")[-1].lower())
    return columns


def validate_select(sql: str) -> bool:
    """校验是否为安全的受限 SELECT：非法返回 False（不抛异常）。"""
    if not isinstance(sql, str):
        return False
    candidate = sql.strip()
    if "--" in candidate or "/*" in candidate or "*/" in candidate:
        return False
    candidate = candidate.rstrip(";").strip()
    if ";" in candidate:
        return False  # 多语句注入
    if not re.match(r"^select\b", candidate, re.IGNORECASE):
        return False
    sanitized = _strip_strings(candidate)
    if _BANNED_KEYWORDS.search(sanitized):
        return False
    tables = re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", sanitized, re.IGNORECASE)
    if not tables or any(t.lower() not in ALLOWED_TABLES for t in tables):
        return False
    if any(column not in ALL_COLUMNS for column in _projection_columns(sanitized)):
        return False
    return True


def _ensure_limit(sql: str, limit: int) -> str:
    candidate = sql.strip().rstrip(";").strip()
    return candidate if _LIMIT_RE.search(candidate) else f"{candidate} LIMIT {int(limit)}"


# ---------------------------------------------------------------------------
# Text2SQL
# ---------------------------------------------------------------------------
class Text2SQL:
    """自然语言 -> 受限 SELECT -> SQLite 执行。"""

    def __init__(self, connection: sqlite3.Connection | None = None,
                 *, default_limit: int = 20) -> None:
        if default_limit <= 0:
            raise ValueError("default_limit 必须为正整数")
        self.conn = connection or create_demo_db()
        self.default_limit = default_limit

    def _limit_from(self, question: str) -> int:
        match = re.search(r"(?:前|top|limit|取)\s*(\d+)\s*(?:个|条|条记录)?", question,
                          re.IGNORECASE)
        return min(int(match.group(1)), 100) if match else self.default_limit

    @staticmethod
    def _record_id(question: str) -> str | None:
        # 中文与字母之间不存在 \\b 边界，故不依赖单词边界
        match = re.search(r"([A-Z]{1,3}\d{3,4})", question.upper())
        return match.group(1) if match else None

    def generate(self, question: str) -> tuple[str, tuple[Any, ...]]:
        """返回 ``(sql, params)``。无法识别时给出安全的产品清单查询。"""
        question = (question or "").strip()
        limit = self._limit_from(question)
        record_id = self._record_id(question)

        def finish(sql: str, params: tuple[Any, ...] = ()) -> tuple[str, tuple[Any, ...]]:
            return _ensure_limit(sql, limit), params

        if "订单" in question and record_id and record_id.startswith("O"):
            return finish(
                "SELECT order_id, product_id, quantity, unit_price FROM order_items "
                "WHERE order_id = ?", (record_id,),
            )
        if "库存" in question or "缺货" in question or "不足" in question:
            threshold = 10 if "不足" in question or "缺货" in question else 0
            return finish(
                "SELECT id, name, category, price, stock FROM products WHERE stock < ?",
                (threshold,),
            )
        if "订单" in question:
            return finish("SELECT id, customer_id, total, status FROM orders")
        for category in ("数码", "家具", "家居", "服装", "食品", "办公"):
            if category in question:
                return finish(
                    "SELECT id, name, category, price, stock FROM products "
                    "WHERE category = ?", (category,),
                )
        if "最贵" in question or "价格最高" in question or "最高价" in question:
            return finish("SELECT id, name, price FROM products ORDER BY price DESC")
        if "便宜" in question or "最低价" in question or "价格最低" in question:
            return finish("SELECT id, name, price FROM products ORDER BY price ASC")
        if "价格" in question or "多少钱" in question:
            return finish("SELECT id, name, price FROM products")
        return finish("SELECT id, name, category, price, stock FROM products")

    def validate(self, sql: str) -> bool:
        return validate_select(sql)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> SQLResult:
        """校验并执行 SQL；非法 SQL 抛 ``ValueError``，自动补 LIMIT。"""
        if not self.validate(sql):
            raise ValueError(f"拒绝执行非白名单或不安全的 SQL: {sql!r}")
        safe_sql = _ensure_limit(sql, self.default_limit)
        cursor = self.conn.execute(safe_sql, params)
        rows = cursor.fetchall()
        return SQLResult(
            sql=safe_sql, params=tuple(params),
            columns=[description[0] for description in cursor.description],
            rows=[tuple(row) for row in rows],
        )

    def run(self, question: str) -> SQLResult:
        """端到端：自然语言 -> SQL -> 校验 -> 执行。"""
        sql, params = self.generate(question)
        return self.execute(sql, params)


# ---------------------------------------------------------------------------
# Text2Cypher（只生成，不执行）
# ---------------------------------------------------------------------------
class Text2Cypher:
    """确定性 Cypher 模板生成器。接 Neo4j 时只需实现 ``execute``。"""

    def __init__(self) -> None:
        self.supported_patterns = (
            "product_category", "order_products", "category_products",
            "policy_keywords", "generic",
        )

    def generate(self, question: str, limit: int = 20) -> CypherQuery:
        question = (question or "").strip()
        record_id = Text2SQL._record_id(question)

        if "类目" in question or "分类" in question:
            for category in ("数码", "家具", "家居", "服装", "食品"):
                if category in question:
                    return CypherQuery(
                        "MATCH (p:Product)-[:BELONGS_TO]->(c:Category {name: $category}) "
                        "RETURN p.name AS product, c.name AS category LIMIT $limit",
                        {"category": category, "limit": limit}, "category_products",
                    )
            if record_id:
                return CypherQuery(
                    "MATCH (p:Product {id: $id})-[:BELONGS_TO]->(c:Category) "
                    "RETURN p.name AS product, c.name AS category",
                    {"id": record_id}, "product_category",
                )
        if "订单" in question and record_id:
            return CypherQuery(
                "MATCH (o:Order {id: $id})-[:CONTAINS]->(p:Product) "
                "RETURN p.id AS product_id, p.name AS product",
                {"id": record_id}, "order_products",
            )
        if "政策" in question or "关键词" in question:
            keyword = next((k for k in ("退货", "配送", "发票", "优惠", "质保")
                            if k in question), "")
            return CypherQuery(
                "MATCH (p:Policy)-[:MENTIONS]->(k:Keyword) "
                "WHERE k.name = $keyword RETURN p.title AS policy, k.name AS keyword "
                "LIMIT $limit",
                {"keyword": keyword, "limit": limit}, "policy_keywords",
            )
        return CypherQuery(
            "MATCH (n) RETURN n LIMIT $limit", {"limit": limit}, "generic",
        )

    def execute(self, query: CypherQuery) -> None:
        """预留接口：本离线实现不连接图数据库。"""
        raise NotImplementedError("Text2Cypher 仅生成 Cypher，接入 Neo4j 后可实现 execute")
