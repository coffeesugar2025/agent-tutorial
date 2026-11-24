"""工具设计学注册表（总纲 2.3 / 2.4，最被低估的一章）。

之前 10 个 MCP 工具有 name/description/schema，但缺「何时不该用」、稳定错误码、
返回 token 预算、幂等标注、动态加载与工具检索。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.capabilities.context import estimate_tokens


@dataclass
class ToolSpec:
    name: str
    description: str
    when_to_use: str
    when_not_to_use: str
    args_schema: dict[str, Any]
    returns: str
    error_codes: dict[str, str]
    max_output_tokens: int = 500
    side_effect: str = "read_only"       # read_only | idempotent_write | irreversible
    idempotent: bool = True
    risk: str = "low"
    acl: tuple[str, ...] = ("catalog:read",)

    def card(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "when_to_use": self.when_to_use, "when_not_to_use": self.when_not_to_use,
                "args_schema": self.args_schema, "returns": self.returns,
                "error_codes": self.error_codes, "max_output_tokens": self.max_output_tokens,
                "side_effect": self.side_effect, "idempotent": self.idempotent,
                "risk": self.risk, "acl": list(self.acl)}


COMMON_ERRORS = {
    "E_NOT_FOUND": "资源不存在；请核对 SKU / 订单号后重试",
    "E_FORBIDDEN": "无权访问该资源；不要改 user_id，转人工",
    "E_INVALID_ARG": "参数不合法；按 schema 修正后重试（可重试分类=validation）",
    "E_OUT_OF_STOCK": "库存不足；推荐替代商品",
    "E_UPSTREAM": "上游暂不可用；可重试或走降级",
}


def default_specs() -> list[ToolSpec]:
    return [
        ToolSpec("search_products", "按关键词检索商品，返回 sku/名称/价格/库存",
                 "用户找商品、比价、看有没有货",
                 "用户问订单/物流/售后时不要用；不要用空关键词全表拖库",
                 {"keyword": "str", "limit": "int<=10"}, "products[] + total",
                 COMMON_ERRORS, 400, "read_only", True, "low"),
        ToolSpec("calculate_price", "按 SKU、数量、券码计算到手价与优惠拆解",
                 "用户问券后价/到手价/优惠多少",
                 "未确认商品 SKU 时不要猜；不要用于订单历史金额",
                 {"sku": "str", "quantity": "int>0", "coupon_code": "str?"},
                 "subtotal/discount/payable", COMMON_ERRORS, 200, "read_only", True, "low"),
        ToolSpec("get_order", "按订单号 + 归属用户查询订单状态与物流节点",
                 "用户提供了明确订单号",
                 "没有订单号就不要编；绝不返回其他 user_id 的订单",
                 {"order_id": "str", "user_id": "str(injected)"}, "order object",
                 COMMON_ERRORS, 300, "read_only", True, "medium", ("order:read",)),
        ToolSpec("check_after_sale_eligibility", "判定订单是否符合退货/价保资格",
                 "用户问能不能退/能不能价保",
                 "不要据此执行退款；资格判定不等于已办理",
                 {"order_id": "str", "user_id": "str(injected)"}, "eligible+reason",
                 COMMON_ERRORS, 200, "read_only", True, "medium", ("order:read",)),
        ToolSpec("apply_refund", "提交退款申请（写操作）",
                 "仅在人工审批通过且金额/订单校验通过后",
                 "无审批单、低置信、金额超阈值时一律不得调用",
                 {"order_id": "str", "amount": "float"}, "approval_id",
                 COMMON_ERRORS, 150, "irreversible", False, "high", ("order:write",)),
    ]


class ToolRegistry:
    def __init__(self) -> None:
        self._specs = {s.name: s for s in default_specs()}

    def card(self, name: str) -> dict[str, Any]:
        s = self._specs.get(name)
        return s.card() if s else {"error": "E_NOT_FOUND"}

    def dynamic_load(self, intents: list[str], limit: int = 3) -> dict[str, Any]:
        """工具检索 / 动态注入：按意图只加载相关工具定义，降低基础 prompt 体积。"""
        picked = [n for n, s in self._specs.items()
                  if any(k in s.when_to_use + s.description for k in intents)][:limit]
        cards = [self.card(n) for n in picked]
        return {"intents": intents, "loaded": picked,
                "tokens": sum(estimate_tokens(str(c)) for c in cards),
                "saved_vs_all": estimate_tokens(str([self.card(n) for n in self._specs]))
                                - estimate_tokens(str(cards))}

    def validate_output(self, name: str, output: dict[str, Any]) -> dict[str, Any]:
        s = self._specs.get(name)
        if not s:
            return {"ok": False, "code": "E_NOT_FOUND"}
        cost = estimate_tokens(str(output))
        return {"ok": cost <= s.max_output_tokens, "tokens": cost,
                "budget": s.max_output_tokens,
                "action": "ok" if cost <= s.max_output_tokens else "截断/摘要后再入上下文"}

    def side_effect_gate(self, name: str, approval_id: str | None = None) -> dict[str, Any]:
        s = self._specs.get(name)
        if not s:
            return {"allowed": False, "reason": "未注册工具"}
        if s.side_effect == "irreversible" and not approval_id:
            return {"allowed": False, "reason": "不可逆操作必须带审批单", "hitl": True}
        return {"allowed": True, "side_effect": s.side_effect, "idempotent": s.idempotent}


REGISTRY = ToolRegistry()
