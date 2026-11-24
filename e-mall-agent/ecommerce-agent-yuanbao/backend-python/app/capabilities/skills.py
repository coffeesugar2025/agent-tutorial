"""MCP / Skill / Plugin 三层能力注册表。

  MCP Tool   细粒度能力（10 个只读工具），跨客户端复用
  Skill      把多个 Tool 按业务目标组合成可复用工作流，带版本与权限
  Plugin     带生命周期钩子（before / after）的 Skill，可挂载审计、限流、脱敏

三者关系：MCP 是协议层，Skill 是编排层，Plugin 是扩展层。
本模块提供注册表、依赖校验、版本管理、权限门禁与组合调用，全部离线可跑。
"""
from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services import catalog

Handler = Callable[..., dict[str, Any]]


@dataclass
class Skill:
    name: str
    version: str
    description: str
    handler: Handler
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()   # 依赖的 MCP 工具名
    kind: str = "skill"                  # skill | plugin
    hooks: dict[str, Handler] = field(default_factory=dict)
    enabled: bool = True

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version,
                "description": self.description, "kind": self.kind,
                "permissions": list(self.permissions),
                "dependencies": list(self.dependencies),
                "enabled": self.enabled,
                "hooks": sorted(self.hooks)}


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._lock = threading.RLock()
        self._invocations: list[dict[str, Any]] = []

    def register(self, skill: Skill) -> None:
        with self._lock:
            self._skills[skill.name] = skill

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._skills.pop(name, None) is not None

    def discover(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [s.describe() for s in self._skills.values()
                    if kind is None or s.kind == kind]

    def check_dependencies(self, skill: Skill, available: set[str]) -> list[str]:
        return [d for d in skill.dependencies if d not in available]

    def invoke(self, name: str, args: dict[str, Any] | None = None,
               caller_permissions: set[str] | None = None) -> dict[str, Any]:
        args = dict(args or {})
        started = time.perf_counter()
        with self._lock:
            skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"Skill 未注册：{name}")
        if not skill.enabled:
            return {"ok": False, "error": f"Skill {name} 已禁用"}
        perms = set(caller_permissions or set())
        missing = [p for p in skill.permissions if p not in perms]
        if missing:
            return {"ok": False, "error": f"缺少权限：{missing}"}

        before = skill.hooks.get("before")
        after = skill.hooks.get("after")
        if before:
            args = before(**args) or args
        result = skill.handler(**args)
        if after:
            after(result=result, args=args)

        elapsed = int((time.perf_counter() - started) * 1000)
        with self._lock:
            self._invocations.append({"skill": name, "version": skill.version,
                                      "elapsed_ms": elapsed, "at": time.time()})
        return {"ok": True, "skill": name, "version": skill.version,
                "result": result, "elapsed_ms": elapsed}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"skills": len(self._skills), "invocations": len(self._invocations),
                    "recent": self._invocations[-5:]}


REGISTRY = SkillRegistry()


# ---------------------------------------------------------------- 内置 Skills
def _recommend_with_coupons(budget: float = 500.0, user_id: str = "u_1001") -> dict[str, Any]:
    products = catalog.recommend_products(budget=budget)
    coupons = catalog.list_coupons(user_id)
    return {"products": products.get("products", []),
            "coupons": coupons.get("coupons", []),
            "budget": budget, "product_count": len(products.get("products", []))}


def _after_sale_judge(order_id: str = "EC20261105002",
                      user_id: str = "u_1001") -> dict[str, Any]:
    eligibility = catalog.check_after_sale_eligibility(order_id, user_id)
    policy = catalog.get_after_sale_policy("退货")
    return {"eligibility": eligibility, "policy": policy}


def _order_overview(order_id: str = "EC20261118001",
                    user_id: str = "u_1001") -> dict[str, Any]:
    order = catalog.get_order(order_id, user_id)
    orders = catalog.list_user_orders(user_id, limit=3)
    return {"order": order.get("order"), "orders": orders.get("orders", [])}


def _price_check(sku: str = "SKU-1001", coupon_code: str = "FULL100") -> dict[str, Any]:
    price = catalog.calculate_price(sku, 1, coupon_code)
    stock = catalog.check_inventory(sku)
    return {"price": price, "stock": stock,
            "consistent": bool(price.get("ok")) and bool(stock.get("ok"))}


def _audit_hook(result: dict[str, Any] | None = None, args: dict[str, Any] | None = None,
                **_: Any) -> None:
    from app.capabilities.observability import METRICS
    METRICS.inc("plugin_after_hook_total", skill="price_check")


def build_default_skills() -> None:
    REGISTRY.register(Skill(
        name="recommend_with_coupons", version="1.0.0",
        description="按预算推荐有货商品，并连带展示当前用户可用券",
        handler=_recommend_with_coupons, permissions=("catalog:read",),
        dependencies=("recommend_products", "list_coupons")))
    REGISTRY.register(Skill(
        name="after_sale_judge", version="1.0.0",
        description="一次调用完成退货资格判定 + 官方政策原文",
        handler=_after_sale_judge, permissions=("catalog:read", "order:read"),
        dependencies=("check_after_sale_eligibility", "get_after_sale_policy")))
    REGISTRY.register(Skill(
        name="order_overview", version="1.0.0",
        description="订单详情 + 该用户最近订单列表",
        handler=_order_overview, permissions=("order:read",),
        dependencies=("get_order", "list_user_orders")))
    REGISTRY.register(Skill(
        name="price_check", version="1.2.0", kind="plugin",
        description="到手价 + 库存一致性校验，带 after 钩子写指标",
        handler=_price_check, permissions=("catalog:read",),
        dependencies=("calculate_price", "check_inventory"),
        hooks={"after": _audit_hook}))


build_default_skills()


def invoke(name: str, args: dict[str, Any] | None = None,
           caller_permissions: set[str] | None = None) -> dict[str, Any]:
    """便捷入口：默认赋予全部演示权限。"""
    perms = caller_permissions or {"catalog:read", "order:read"}
    return REGISTRY.invoke(name, args, perms)


def capability_contract() -> dict[str, Any]:
    return {
        "mcp": {"tools": 10, "protocol": "MCP (stdio / Streamable HTTP)",
                "layer": "协议层，跨客户端复用"},
        "skill": {"count": len([s for s in REGISTRY.discover() if s["kind"] == "skill"]),
                  "layer": "编排层，多工具组合 + 版本 + 权限"},
        "plugin": {"count": len([s for s in REGISTRY.discover() if s["kind"] == "plugin"]),
                   "layer": "扩展层，before/after 生命周期钩子"},
        "gates": ["依赖校验 check_dependencies", "权限门禁 caller_permissions",
                  "启用开关 enabled", "调用留痕 invocations"],
    }
