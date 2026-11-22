"""In-memory domain repository (swap for SQL/ORM in production)."""
from __future__ import annotations

import itertools
import threading

from ..rag.embeddings import tokenize
from .models import Order, OrderItem, Product, User, utcnow


class InMemoryRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ids = itertools.count(1004)
        self._products: dict[str, Product] = {}
        self._orders: dict[str, Order] = {}
        self._users: dict[str, User] = {}
        self._seed()

    def _seed(self) -> None:
        products = [
            Product(id="P001", name="无线降噪耳机 Pro", category="数码", price=899.0, stock=12,
                    tags=["音频", "热销", "降噪"], description="40小时续航，主动降噪，适合通勤与办公。"),
            Product(id="P002", name="便携咖啡机", category="家居", price=359.0, stock=5,
                    tags=["咖啡", "便携"], description="手压萃取，随行制作意式浓缩。"),
            Product(id="P003", name="人体工学椅", category="家具", price=1299.0, stock=3,
                    tags=["办公", "护腰"], description="网布透气，腰托可调，久坐友好。"),
            Product(id="P004", name="智能手表 S2", category="数码", price=1099.0, stock=20,
                    tags=["穿戴", "健康"], description="心率血氧监测，14天续航。"),
            Product(id="P005", name="移动电源 20000mAh", category="数码", price=199.0, stock=50,
                    tags=["充电", "出行"], description="22.5W 快充，可带上飞机。"),
            Product(id="P006", name="机械键盘 87键", category="数码", price=459.0, stock=8,
                    tags=["键盘", "办公"], description="茶轴手感，紧凑布局，支持热插拔。"),
            Product(id="P007", name="空气循环扇", category="家电", price=299.0, stock=0,
                    tags=["风扇", "静音"], description="直流变频，低噪循环送风。"),
            Product(id="P008", name="保温杯 500ml", category="家居", price=129.0, stock=100,
                    tags=["水杯", "保温"], description="316不锈钢，12小时保温。"),
        ]
        for p in products:
            self._products[p.id] = p

        self._orders["O1001"] = Order(
            id="O1001", customer_id="U001",
            items=[OrderItem(product_id="P001", quantity=1, unit_price=899.0),
                   OrderItem(product_id="P005", quantity=1, unit_price=199.0)],
            total=1098.0, status="shipped", created_at="2026-11-18T09:12:00+00:00",
            address="北京市朝阳区示例路 1 号",
        )
        self._orders["O1002"] = Order(
            id="O1002", customer_id="U002",
            items=[OrderItem(product_id="P003", quantity=1, unit_price=1299.0)],
            total=1299.0, status="created", created_at="2026-11-20T14:30:00+00:00",
            address="上海市浦东新区示例路 2 号",
        )
        self._orders["O1003"] = Order(
            id="O1003", customer_id="U001",
            items=[OrderItem(product_id="P006", quantity=2, unit_price=459.0)],
            total=918.0, status="delivered", created_at="2026-11-10T03:05:00+00:00",
            address="北京市朝阳区示例路 1 号",
        )

        self._users = {
            "U001": User(id="U001", name="张三", role="customer", password="123456"),
            "U002": User(id="U002", name="李四", role="customer", password="123456"),
            "S001": User(id="S001", name="王客服", role="service", password="123456"),
            "A001": User(id="A001", name="管理员", role="admin", password="123456"),
        }

    # ---------- users ----------
    def get_user(self, user_id: str) -> User | None:
        with self._lock:
            return self._users.get(user_id)

    def authenticate(self, name: str, password: str) -> User | None:
        with self._lock:
            for user in self._users.values():
                if user.name == name and user.password == password:
                    return user
            return None

    def list_users(self) -> list[dict]:
        with self._lock:
            return [{"id": u.id, "name": u.name, "role": u.role} for u in self._users.values()]

    # ---------- products ----------
    def list_products(self, category: str | None = None) -> list[Product]:
        with self._lock:
            items = list(self._products.values())
        if category:
            items = [p for p in items if p.category == category]
        return items

    def get_product(self, product_id: str) -> Product | None:
        with self._lock:
            return self._products.get(product_id)

    def search_products(self, query: str, limit: int = 5) -> list[Product]:
        q = (query or "").strip().lower()
        if not q:
            return self.list_products()[:limit]
        tokens = [t for t in tokenize(q) if len(t) >= 2]
        scored: list[tuple[int, Product]] = []
        for p in self.list_products():
            haystack = " ".join([p.id, p.name, p.category, p.description, *p.tags]).lower()
            score = sum(len(token) for token in tokens if token in haystack)
            if q in p.name.lower():
                score += 8
            if score:
                scored.append((score, p))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [p for _, p in scored][:limit]

    def get_inventory(self, product_id: str) -> dict | None:
        p = self.get_product(product_id)
        if not p:
            return None
        return {"product_id": p.id, "name": p.name, "stock": p.stock,
                "available": p.stock > 0}

    def decrease_stock(self, product_id: str, quantity: int) -> bool:
        with self._lock:
            p = self._products.get(product_id)
            if not p or p.stock < quantity:
                return False
            p.stock -= quantity
            return True

    # ---------- orders ----------
    def create_order(self, customer_id: str, items: list[dict]) -> Order:
        with self._lock:
            normalized: list[OrderItem] = []
            for item in items:
                pid = str(item.get("product_id", "")).strip()
                qty = int(item.get("quantity", 1))
                product = self._products.get(pid)
                if not product:
                    raise ValueError(f"商品不存在: {pid}")
                if qty < 1:
                    raise ValueError("购买数量必须大于 0")
                if product.stock < qty:
                    raise ValueError(f"库存不足: {product.name} (剩余 {product.stock})")
                normalized.append(OrderItem(product_id=pid, quantity=qty,
                                            unit_price=product.price))
            for line in normalized:
                self._products[line.product_id].stock -= line.quantity
            order_id = f"O{next(self._ids)}"
            order = Order(
                id=order_id, customer_id=customer_id, items=normalized,
                total=round(sum(i.quantity * i.unit_price for i in normalized), 2),
                status="created", created_at=utcnow(),
            )
            self._orders[order_id] = order
            return order

    def get_order(self, order_id: str) -> Order | None:
        with self._lock:
            return self._orders.get(order_id)

    def list_orders(self, customer_id: str | None = None) -> list[Order]:
        with self._lock:
            orders = list(self._orders.values())
        if customer_id:
            orders = [o for o in orders if o.customer_id == customer_id]
        return sorted(orders, key=lambda o: o.created_at, reverse=True)

    def set_order_status(self, order_id: str, status: str) -> Order | None:
        with self._lock:
            order = self._orders.get(order_id)
            if order:
                order.status = status
            return order

    def request_refund(self, order_id: str, reason: str) -> Order | None:
        order = self.set_order_status(order_id, "refund_requested")
        if order:
            # audit trail lives in the order status; full log is in AuditLogger
            order.address = f"{order.address} | refund_reason={reason}"
        return order


_repository: InMemoryRepository | None = None


def get_repository() -> InMemoryRepository:
    global _repository
    if _repository is None:
        _repository = InMemoryRepository()
    return _repository


def reset_repository() -> InMemoryRepository:
    """Test helper: restore seed data."""
    global _repository
    _repository = InMemoryRepository()
    return _repository
