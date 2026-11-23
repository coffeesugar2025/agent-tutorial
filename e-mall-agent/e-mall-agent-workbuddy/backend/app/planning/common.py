"""规划与执行共用的规则：意图拆步、参数提取与工具调用。

这里的规则完全离线、确定性，不依赖任何 API Key，保证测试可重复。
"""
from __future__ import annotations

import json
import re
from typing import Any

from .models import PlanStep

# (工具提示, 关键词元组, 步骤描述)，按执行优先级排列
INTENT_RULES: list[tuple[str, tuple[str, ...], str]] = [
    ("rag_search", ("政策", "保修", "配送", "发票", "优惠券", "运费", "规则", "怎么", "如何"),
     "检索售后/配送/发票等知识库政策"),
    ("search_products", ("商品", "推荐", "价格", "多少钱", "便宜", "搜索", "找",
                         "耳机", "键盘", "椅子", "手表", "咖啡", "水杯", "充电"),
     "按关键词搜索在售商品"),
    ("check_inventory", ("库存", "有货", "还有吗", "剩多少"), "查询指定商品实时库存"),
    ("list_orders", ("我的订单", "订单列表", "所有订单"), "列出客户订单"),
    ("get_order", ("订单状态", "物流", "发货", "查订单", "订单"), "查询订单明细与状态"),
    ("create_order", ("下单", "购买", "我要买", "来一", "来个"), "为客户创建订单"),
    ("initiate_refund", ("退款", "退货", "售后", "投诉", "换货"), "发起退款申请"),
]

_STOP_WORDS = ("请", "帮我", "我想", "一下", "请问", "给我", "我要", "然后", "并且")


def extract_steps(goal: str) -> list[PlanStep]:
    """根据目标中的关键词确定性地拆出步骤序列。

    步骤之间构成线性依赖链：除第一步外，每步都依赖前一步的 id。
    未命中任何规则时生成一个 ``tool_hint`` 为空的通用回答步骤。

    Args:
        goal: 用户目标文本。

    Returns:
        带 id 与依赖关系的 ``PlanStep`` 列表。
    """
    text = (goal or "").lower()
    hints: list[tuple[str, str]] = []
    for tool_hint, keywords, description in INTENT_RULES:
        if any(keyword in text for keyword in keywords):
            hints.append((tool_hint, description))
    if not hints:
        hints.append(("", "直接回答用户问题"))

    steps: list[PlanStep] = []
    for index, (tool_hint, description) in enumerate(hints, start=1):
        depends_on = [f"s{index - 1}"] if index > 1 else []
        steps.append(
            PlanStep(
                id=f"s{index}",
                description=description,
                tool_hint=tool_hint,
                depends_on=depends_on,
            )
        )
    return steps


def _extract_id(text: str, pattern: str, default: str) -> str:
    """按正则提取编号，未命中时返回默认值。"""
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0).upper() if match else default


def build_action_input(tool_hint: str, goal: str, user: Any = None) -> dict[str, Any]:
    """为某个工具提示构造调用参数。

    Args:
        tool_hint: 工具名。
        goal: 用户目标文本，用于提取商品/订单编号。
        user: 用户对象，用于提取客户 id。

    Returns:
        可直接传给 LangChain 工具的字典参数。
    """
    text = goal or ""
    user_id = getattr(user, "id", None) or "U001"
    if tool_hint == "search_products":
        query = text
        for word in _STOP_WORDS:
            query = query.replace(word, " ")
        return {"query": query.strip() or "商品"}
    if tool_hint == "check_inventory":
        return {"product_id": _extract_id(text, r"p\d{3,5}", "P001")}
    if tool_hint == "create_order":
        pid = _extract_id(text, r"p\d{3,5}", "P001")
        match = re.search(r"(\d+)\s*(件|个|台|把)", text)
        quantity = int(match.group(1)) if match else 1
        items = json.dumps([{"product_id": pid, "quantity": quantity}], ensure_ascii=False)
        return {"customer_id": user_id, "items_json": items}
    if tool_hint == "list_orders":
        return {"customer_id": user_id}
    if tool_hint == "get_order":
        return {"order_id": _extract_id(text, r"o\d{3,5}", "O1001")}
    if tool_hint == "initiate_refund":
        return {"order_id": _extract_id(text, r"o\d{3,5}", "O1001"),
                "reason": text.strip()[:80] or "用户申请"}
    if tool_hint == "rag_search":
        return {"query": text.strip()[:120] or "售后政策"}
    return {}


def is_failure(output: str) -> bool:
    """判断工具输出是否表示失败（含 error 或权限拒绝标记）。"""
    lowered = (output or "").lower()
    return '"error"' in lowered or "permission_denied" in lowered or "失败" in lowered


def call_tool(
    tools: list[Any], tool_hint: str, action_input: dict[str, Any]
) -> str:
    """按工具名调用绑定的工具，返回字符串形式的观察结果。

    工具可以是 LangChain ``BaseTool``（用 ``invoke``），也可以是普通函数
    （用关键字参数调用）。调用异常会被转成含 ``error`` 的 JSON 字符串，
    便于上层统一判定失败。

    Args:
        tools: 已绑定的工具列表。
        tool_hint: 工具名。
        action_input: 调用参数。

    Returns:
        工具输出字符串。
    """
    for tool in tools:
        if getattr(tool, "name", None) == tool_hint:
            try:
                return str(tool.invoke(action_input))
            except Exception as exc:  # noqa: BLE001 - 转成结构化错误观察
                return json.dumps({"error": str(exc)}, ensure_ascii=False)
    for fn in tools:
        if getattr(fn, "__name__", None) == tool_hint:
            try:
                return str(fn(**action_input))
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps({"error": f"未知工具 {tool_hint}"}, ensure_ascii=False)
