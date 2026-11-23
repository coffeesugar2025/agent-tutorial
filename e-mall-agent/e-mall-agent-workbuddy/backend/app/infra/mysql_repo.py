"""MySQL 仓储适配器：接口与 InMemoryRepository 完全对齐。

未配置 ECOM_MYSQL_URL 或缺少 pymysql 时，所有方法委托给内存仓储，
status() 返回明确的 not_configured 说明。pymysql 只在首次真实调用时导入，
不配置时不会触发任何外部依赖。
"""
from __future__ import annotations

import importlib.util
import itertools
import json
from typing import Any
from urllib.parse import urlparse

from ..domain.models import Order, OrderItem, Product, User, utcnow
from ..domain.repository import InMemoryRepository
from .settings import InfraSettings

SCHEMA_SQL = """
-- 电商基础表结构（MySQL 8.0+）
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'customer',
    password VARCHAR(128) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(64) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    stock INT NOT NULL DEFAULT 0,
    tags TEXT,
    description TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS orders (
    id VARCHAR(32) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL,
    total DECIMAL(10,2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    created_at VARCHAR(64) NOT NULL,
    address TEXT,
    KEY idx_customer (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(32) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    KEY idx_order (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 种子数据（与 InMemoryRepository 保持一致）
INSERT IGNORE INTO users (id, name, role, password) VALUES
    ('U001', '张三', 'customer', '123456'),
    ('U002', '李四', 'customer', '123456'),
    ('S001', '王客服', 'service', '123456'),
    ('A001', '管理员', 'admin', '123456');

INSERT IGNORE INTO products (id, name, category, price, stock, tags, description) VALUES
    ('P001', '无线降噪耳机 Pro', '数码', 899.00, 12, '["音频","热销","降噪"]', '40小时续航，主动降噪。'),
    ('P002', '便携咖啡机', '家居', 359.00, 5, '["咖啡","便携"]', '手压萃取，随行制作意式浓缩。'),
    ('P003', '人体工学椅', '家具', 1299.00, 3, '["办公","护腰"]', '网布透气，腰托可调。'),
    ('P004', '智能手表 S2', '数码', 1099.00, 20, '["穿戴","健康"]', '心率血氧监测，14天续航。'),
    ('P005', '移动电源 20000mAh', '数码', 199.00, 50, '["充电","出行"]', '22.5W 快充。'),
    ('P006', '机械键盘 87键', '数码', 459.00, 8, '["键盘","办公"]', '茶轴手感，支持热插拔。'),
    ('P007', '空气循环扇', '家电', 299.00, 0, '["风扇","静音"]', '直流变频，低噪送风。'),
    ('P008', '保温杯 500ml', '家居', 129.00, 100, '["水杯","保温"]', '316不锈钢，12小时保温。');

INSERT IGNORE INTO orders (id, customer_id, total, status, created_at, address) VALUES
    ('O1001', 'U001', 1098.00, 'shipped', '2026-11-18T09:12:00+00:00', '北京市朝阳区示例路 1 号'),
    ('O1002', 'U002', 1299.00, 'created', '2026-11-20T14:30:00+00:00', '上海市浦东新区示例路 2 号'),
    ('O1003', 'U001', 918.00, 'delivered', '2026-11-10T03:05:00+00:00', '北京市朝阳区示例路 1 号');

INSERT IGNORE INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    ('O1001', 'P001', 1, 899.00),
    ('O1001', 'P005', 1, 199.00),
    ('O1002', 'P003', 1, 1299.00),
    ('O1003', 'P006', 2, 459.00);
"""
# 兼容别名：便于以 schema_sql 名称引用同一份建表/种子脚本
schema_sql = SCHEMA_SQL


class MySQLRepository:
    """MySQL 后端仓储；未配置时行为与 InMemoryRepository 完全一致。"""

    def __init__(self, url: str | None = None,
                 settings: InfraSettings | None = None) -> None:
        cfg = settings or InfraSettings.from_env()
        self.url = url if url is not None else cfg.mysql_url
        self._fallback = InMemoryRepository()
        self._conn: Any = None
        self._ids = itertools.count(1004)

    @property
    def configured(self) -> bool:
        """是否已显式配置 MySQL URL。"""
        return bool(self.url)

    @staticmethod
    def _driver_available() -> bool:
        return importlib.util.find_spec("pymysql") is not None

    def _connect(self) -> Any:
        """懒加载 pymysql 连接；不可用时返回 None 触发内存回退。"""
        if not self.configured or not self._driver_available():
            return None
        if self._conn is None:
            try:
                import pymysql  # type: ignore

                parsed = urlparse(self.url.replace("mysql+pymysql://", "mysql://"))
                self._conn = pymysql.connect(
                    host=parsed.hostname or "127.0.0.1",
                    port=parsed.port or 3306,
                    user=parsed.username or "root",
                    password=parsed.password or "",
                    database=(parsed.path or "/ecom").lstrip("/") or "ecom",
                    charset="utf8mb4",
                )
            except Exception:
                return None
        return self._conn

    def _query(self, sql: str, args: tuple = ()) -> list[dict] | None:
        """返回 dict 行列表；None 表示后端不可用（区别于查询无结果）。"""
        conn = self._connect()
        if conn is None:
            return None
        cursor = None
        try:
            import pymysql  # type: ignore

            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(sql, args)
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return None
        finally:
            if cursor is not None:
                cursor.close()

    def _execute(self, sql: str, args: tuple = ()) -> int | None:
        """执行单条写操作并提交，返回影响行数；None 表示后端不可用。"""
        conn = self._connect()
        if conn is None:
            return None
        cursor = None
        try:
            cursor = conn.cursor()
            affected = cursor.execute(sql, args)
            conn.commit()
            return int(affected)
        except Exception:
            conn.rollback()
            return None
        finally:
            if cursor is not None:
                cursor.close()

    def _transaction(self, statements: list[tuple[str, tuple]]) -> bool:
        """在一个事务里顺序执行多条写操作。"""
        conn = self._connect()
        if conn is None:
            return False
        cursor = None
        try:
            cursor = conn.cursor()
            for sql, args in statements:
                cursor.execute(sql, args)
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            if cursor is not None:
                cursor.close()

    # ---------- 行 -> 领域模型 ----------
    @staticmethod
    def _product(row: dict) -> Product:
        try:
            tags = json.loads(row.get("tags") or "[]")
        except (TypeError, ValueError):
            tags = []
        return Product(id=row["id"], name=row["name"], category=row["category"],
                       price=float(row["price"]), stock=int(row["stock"]),
                       tags=tags if isinstance(tags, list) else [],
                       description=row.get("description") or "")

    @staticmethod
    def _order(row: dict, items: list[dict]) -> Order:
        return Order(
            id=row["id"], customer_id=row["customer_id"],
            items=[OrderItem(product_id=i["product_id"], quantity=int(i["quantity"]),
                             unit_price=float(i["unit_price"])) for i in items],
            total=float(row["total"]), status=row["status"],
            created_at=row["created_at"], address=row.get("address") or "",
        )

    def _load_order(self, order_id: str) -> Order | None:
        rows = self._query("SELECT * FROM orders WHERE id=%s", (order_id,))
        if rows is None:
            return None
        if not rows:
            return None
        items = self._query(
            "SELECT product_id, quantity, unit_price FROM order_items "
            "WHERE order_id=%s ORDER BY id", (order_id,))
        if items is None:
            return None
        return self._order(rows[0], items)

    # ---------- users ----------
    def get_user(self, user_id: str) -> User | None:
        rows = self._query("SELECT id, name, role, password FROM users WHERE id=%s", (user_id,))
        if rows is None:
            return self._fallback.get_user(user_id)
        return User(**rows[0]) if rows else None

    def authenticate(self, name: str, password: str) -> User | None:
        rows = self._query(
            "SELECT id, name, role, password FROM users WHERE name=%s AND password=%s",
            (name, password))
        if rows is None:
            return self._fallback.authenticate(name, password)
        return User(**rows[0]) if rows else None

    def list_users(self) -> list[dict]:
        rows = self._query("SELECT id, name, role FROM users ORDER BY id")
        if rows is None:
            return self._fallback.list_users()
        return [{"id": r["id"], "name": r["name"], "role": r["role"]} for r in rows]

    # ---------- products ----------
    def list_products(self, category: str | None = None) -> list[Product]:
        if category:
            rows = self._query("SELECT * FROM products WHERE category=%s ORDER BY id", (category,))
        else:
            rows = self._query("SELECT * FROM products ORDER BY id")
        if rows is None:
            return self._fallback.list_products(category)
        return [self._product(r) for r in rows]

    def get_product(self, product_id: str) -> Product | None:
        rows = self._query("SELECT * FROM products WHERE id=%s", (product_id,))
        if rows is None:
            return self._fallback.get_product(product_id)
        return self._product(rows[0]) if rows else None

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        keyword = (query or "").strip()
        if not keyword:
            return self.list_products()[:limit]
        like = f"%{keyword}%"
        rows = self._query(
            "SELECT * FROM products WHERE name LIKE %s OR category LIKE %s "
            "OR description LIKE %s OR tags LIKE %s ORDER BY id LIMIT %s",
            (like, like, like, like, limit))
        if rows is None:
            return self._fallback.search_products(query, limit)
        return [self._product(r) for r in rows]

    def get_inventory(self, product_id: str) -> dict | None:
        product = self.get_product(product_id)
        if not product:
            return None
        return {"product_id": product.id, "name": product.name, "stock": product.stock,
                "available": product.stock > 0}

    def decrease_stock(self, product_id: str, quantity: int) -> bool:
        affected = self._execute(
            "UPDATE products SET stock=stock-%s WHERE id=%s AND stock>=%s",
            (quantity, product_id, quantity))
        if affected is None:
            return self._fallback.decrease_stock(product_id, quantity)
        return affected > 0

    # ---------- orders ----------
    def create_order(self, customer_id: str, items: list[dict]) -> Order:
        if self._connect() is None:
            return self._fallback.create_order(customer_id, items)
        normalized: list[tuple[dict, OrderItem]] = []
        for item in items:
            product_id = str(item.get("product_id", "")).strip()
            quantity = int(item.get("quantity", 1))
            if quantity < 1:
                raise ValueError("购买数量必须大于 0")
            rows = self._query("SELECT id, name, price, stock FROM products WHERE id=%s",
                               (product_id,))
            if rows is None:
                return self._fallback.create_order(customer_id, items)
            if not rows:
                raise ValueError(f"商品不存在: {product_id}")
            product = rows[0]
            if int(product["stock"]) < quantity:
                raise ValueError(f"库存不足: {product['name']} (剩余 {product['stock']})")
            line = OrderItem(product_id=product_id, quantity=quantity,
                             unit_price=float(product["price"]))
            normalized.append((product, line))
        order_id = f"O{next(self._ids)}"
        total = round(sum(line.quantity * line.unit_price for _, line in normalized), 2)
        created_at = utcnow()
        statements: list[tuple[str, tuple]] = [
            ("UPDATE products SET stock=stock-%s WHERE id=%s",
             (line.quantity, line.product_id)) for _, line in normalized
        ]
        statements.append((
            "INSERT INTO orders (id, customer_id, total, status, created_at, address) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (order_id, customer_id, total, "created", created_at, "")))
        for _, line in normalized:
            statements.append((
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (%s, %s, %s, %s)",
                (order_id, line.product_id, line.quantity, line.unit_price)))
        if not self._transaction(statements):
            raise RuntimeError("创建订单失败：数据库写入错误")
        return Order(id=order_id, customer_id=customer_id,
                     items=[line for _, line in normalized], total=total,
                     status="created", created_at=created_at)

    def get_order(self, order_id: str) -> Order | None:
        if self._connect() is None:
            return self._fallback.get_order(order_id)
        order = self._load_order(order_id)
        return order if order is not None else self._fallback.get_order(order_id)

    def list_orders(self, customer_id: str | None = None) -> list[Order]:
        if customer_id:
            rows = self._query("SELECT * FROM orders WHERE customer_id=%s "
                               "ORDER BY created_at DESC", (customer_id,))
        else:
            rows = self._query("SELECT * FROM orders ORDER BY created_at DESC")
        if rows is None:
            return self._fallback.list_orders(customer_id)
        orders = []
        for row in rows:
            items = self._query(
                "SELECT product_id, quantity, unit_price FROM order_items "
                "WHERE order_id=%s ORDER BY id", (row["id"],))
            if items is None:
                return self._fallback.list_orders(customer_id)
            orders.append(self._order(row, items))
        return orders

    def set_order_status(self, order_id: str, status: str) -> Order | None:
        affected = self._execute("UPDATE orders SET status=%s WHERE id=%s",
                                 (status, order_id))
        if affected is None:
            return self._fallback.set_order_status(order_id, status)
        if affected == 0:
            return None
        order = self._load_order(order_id)
        return order if order is not None else self._fallback.get_order(order_id)

    def request_refund(self, order_id: str, reason: str) -> Order | None:
        if self._connect() is None:
            return self._fallback.request_refund(order_id, reason)
        order = self.set_order_status(order_id, "refund_requested")
        if order:
            address = f"{order.address} | refund_reason={reason}"
            self._execute("UPDATE orders SET address=%s WHERE id=%s", (address, order_id))
            order.address = address
        return order

    def initialize(self) -> None:
        """按 SCHEMA_SQL 初始化表与种子数据（需要真实 MySQL 后端）。"""
        conn = self._connect()
        if conn is None:
            return
        cursor = conn.cursor()
        try:
            for statement in SCHEMA_SQL.split(";"):
                if statement.strip():
                    cursor.execute(statement)
            conn.commit()
        finally:
            cursor.close()

    def status(self) -> dict[str, Any]:
        """组件状态（不建立网络连接）。"""
        active = self.configured and self._driver_available()
        if not self.configured:
            detail = "not_configured: ECOM_MYSQL_URL 未配置，回退到 InMemoryRepository"
        elif not self._driver_available():
            detail = "not_configured: 缺少 pymysql 驱动，回退到 InMemoryRepository"
        else:
            detail = "MySQL 驱动可用，使用 MySQL 后端"
        return {
            "configured": self.configured,
            "active": active,
            "backend": "mysql" if active else "memory",
            "detail": detail,
        }
