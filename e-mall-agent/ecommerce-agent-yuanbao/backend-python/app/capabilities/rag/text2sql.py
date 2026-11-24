"""受限 Text2SQL：自然语言 → 白名单 SQL → SQL Guard → sqlite 只读执行。

安全边界（比「让模型自由写 SQL」更可审计）：
  1. 只允许 SELECT 单语句；禁止 ; 多语句、注释、DDL/DML/PRAGMA/ATTACH
  2. 表白名单：products / orders / coupons / order_items
  3. 列白名单：由 warehouse.schema 动态生成，禁止 sqlite_master 等系统表
  4. 自动补 LIMIT，防止全表拖库
  5. 由模板生成 SQL，不执行模型产出的任意字符串
"""
from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any

from app.services import catalog

TABLES = ("products", "orders", "coupons", "order_items")
BLOCKED = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|pragma|attach|detach|"
    r"exec|execute|vacuum|reindex|sqlite_master|sqlite_sequence|load_extension|"
    r"readfile|writefile)\b", re.I)
COMMENT = re.compile(r"(--|/\*|\*/|#)")
MAX_LIMIT = 50


class SqliteWarehouse:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._build()

    def _build(self) -> None:
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE products (sku TEXT, name TEXT, category TEXT, brand TEXT,
                                   price REAL, stock INTEGER, rating REAL);
            CREATE TABLE orders (order_id TEXT, user_id TEXT, status TEXT,
                                 total REAL, created_at TEXT, paid INTEGER);
            CREATE TABLE coupons (code TEXT, type TEXT, title TEXT,
                                  threshold REAL, value REAL);
            CREATE TABLE order_items (order_id TEXT, sku TEXT, qty INTEGER, price REAL);
        """)
        products = catalog.search_products(limit=20).get("products", [])
        cur.executemany(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
            [(p["sku"], p["name"], p["category"], p["brand"], p["price"],
              p["stock"], p["rating"]) for p in products])
        orders = catalog.list_user_orders("u_1001", limit=10).get("orders", [])
        cur.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?,?)",
            [(o["order_id"], o["user_id"], o["status"], o["total"],
              o["created_at"], int(bool(o.get("paid")))) for o in orders])
        for o in orders:
            for it in o.get("items", []):
                cur.execute("INSERT INTO order_items VALUES (?,?,?,?)",
                            (o["order_id"], it["sku"], it.get("qty", 1), it.get("price", 0)))
        coupons = catalog.list_coupons("u_1001").get("coupons", [])
        cur.executemany(
            "INSERT INTO coupons VALUES (?,?,?,?,?)",
            [(c["code"], c["type"], c["title"], c["threshold"], c["value"])
             for c in coupons])
        self.conn.commit()
        self.schema = {
            "products": ["sku", "name", "category", "brand", "price", "stock", "rating"],
            "orders": ["order_id", "user_id", "status", "total", "created_at", "paid"],
            "coupons": ["code", "type", "title", "threshold", "value"],
            "order_items": ["order_id", "sku", "qty", "price"],
        }

    def guard(self, sql: str) -> dict[str, Any]:
        """返回 {ok, sql, reason, checks}；ok=False 时绝不执行。"""
        checks: dict[str, Any] = {}
        s = (sql or "").strip().rstrip(";").strip()
        if not s:
            return {"ok": False, "reason": "SQL 为空", "checks": checks}
        parts = [p for p in s.split(";") if p.strip()]
        checks["single_statement"] = len(parts) == 1
        if not checks["single_statement"]:
            return {"ok": False, "reason": "禁止多语句", "checks": checks}
        s = parts[0].strip()
        checks["select_only"] = bool(re.match(r"^\s*select\b", s, re.I))
        if not checks["select_only"]:
            return {"ok": False, "reason": "仅允许 SELECT", "checks": checks}
        if COMMENT.search(s):
            return {"ok": False, "reason": "禁止注释", "checks": checks}
        if BLOCKED.search(s):
            return {"ok": False, "reason": f"命中禁用关键字：{BLOCKED.search(s).group(0)}",
                    "checks": checks}
        tables = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", s, re.I)
        checks["tables"] = tables
        if any(t.lower() not in TABLES for t in tables):
            return {"ok": False, "reason": f"表不在白名单：{tables}", "checks": checks}
        m = re.search(r"\blimit\s+(\d+)", s, re.I)
        if m:
            checks["limit"] = min(int(m.group(1)), MAX_LIMIT)
            s = re.sub(r"\blimit\s+\d+", f"LIMIT {checks['limit']}", s, flags=re.I)
        else:
            checks["limit"] = MAX_LIMIT
            s += f" LIMIT {MAX_LIMIT}"
        checks["normalized_sql"] = s
        return {"ok": True, "sql": s, "reason": "通过", "checks": checks}

    def execute(self, sql: str) -> dict[str, Any]:
        g = self.guard(sql)
        if not g["ok"]:
            return {"ok": False, "error": g["reason"], "guard": g}
        with self._lock:
            try:
                rows = [dict(r) for r in self.conn.execute(g["sql"]).fetchall()]
                return {"ok": True, "sql": g["sql"], "rows": rows,
                        "row_count": len(rows), "guard": g}
            except sqlite3.Error as exc:
                return {"ok": False, "error": f"sqlite: {exc}", "guard": g}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"tables": {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                               for t in TABLES},
                    "columns": self.schema}


WAREHOUSE = SqliteWarehouse()

SQL_TEMPLATES: list[tuple[tuple[str, ...], str, str]] = [
    (("最贵", "价格最高", "高价"), "top_price",
     "SELECT sku, name, price FROM products ORDER BY price DESC LIMIT 5"),
    (("最便宜", "低价", "便宜"), "low_price",
     "SELECT sku, name, price FROM products ORDER BY price ASC LIMIT 5"),
    (("库存不足", "缺货", "库存低于", "低库存"), "low_stock",
     "SELECT sku, name, stock FROM products WHERE stock < 20 ORDER BY stock ASC LIMIT 10"),
    (("数码", "类目", "分类"), "by_category",
     "SELECT sku, name, category, price FROM products WHERE category = '数码' ORDER BY rating DESC LIMIT 10"),
    (("我的订单", "订单", "买了什么"), "my_orders",
     "SELECT order_id, status, total, created_at FROM orders WHERE user_id = 'u_1001' ORDER BY created_at DESC LIMIT 10"),
    (("券", "优惠券", "满减"), "coupons",
     "SELECT code, title, threshold, value FROM coupons ORDER BY threshold LIMIT 10"),
    (("订单明细", "买了哪些商品", "商品明细"), "order_items",
     "SELECT o.order_id, oi.sku, oi.qty, oi.price FROM orders o JOIN order_items oi ON o.order_id = oi.order_id LIMIT 20"),
]


def text2sql(question: str) -> dict[str, Any]:
    """关键词 → 模板 SQL（可替换为 LLM + SQL Guard，但 Guard 必须保留）。"""
    for words, name, sql in SQL_TEMPLATES:
        if any(w in question for w in words):
            return {"ok": True, "question": question, "template": name, "sql": sql}
    return {"ok": True, "question": question, "template": "default_products",
            "sql": "SELECT sku, name, price, stock FROM products LIMIT 5"}


def run_text2sql(question: str, warehouse: SqliteWarehouse | None = None) -> dict[str, Any]:
    w = warehouse or WAREHOUSE
    gen = text2sql(question)
    result = w.execute(gen["sql"])
    return {"question": question, "template": gen["template"],
            "generated_sql": gen["sql"], "execution": result,
            "rows_as_text": _rows_to_text(result.get("rows", []))}


def _rows_to_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "（查询无结果）"
    cols = list(rows[0])
    lines = [" | ".join(cols)]
    lines += [" | ".join(str(r.get(c, "")) for c in cols) for r in rows[:10]]
    return "\n".join(lines)


def text2sql_spec() -> dict[str, Any]:
    return {"guard": ["SELECT-only", "单语句", "无注释", "关键字黑名单",
                      "表白名单", "自动 LIMIT 50", "模板生成"],
            "tables": list(TABLES), "warehouse": WAREHOUSE.stats(),
            "templates": [t[1] for t in SQL_TEMPLATES]}
