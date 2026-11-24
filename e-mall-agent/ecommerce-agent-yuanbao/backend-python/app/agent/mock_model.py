"""脚本化 ChatModel：让整条 create_agent -> MCP ToolNode -> ToolMessage 链路
在没有任何 API Key 的情况下也能真实跑起来（用于本地开发、CI 与演示）。

它不是「跳过 Agent」的假实现：模型仍由 LangChain 1.5 正常调用 bind_tools、
仍能自主产出 tool_calls、仍由 LangGraph ToolNode 执行真实 MCP 工具。
"""
from __future__ import annotations

import json
from typing import Any, Iterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

# 工具名 hint -> 用户意图关键词
_INTENT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("订单", "物流", "快递", "发货", "签收", "单号"), "get_order"),
    (("我的订单", "最近买", "买过", "全部订单"), "list_user_orders"),
    (("退货", "能退", "退款", "七天", "7天", "售后资格"), "check_after_sale_eligibility"),
    (("政策", "保修", "发票", "价保", "换货规定"), "get_after_sale_policy"),
    (("库存", "有货", "缺货", "还有吗", "剩几件"), "check_inventory"),
    (("多少钱", "到手", "优惠", "用券", "券后", "算一下", "价格"), "calculate_price"),
    (("有什么券", "优惠券", "领券"), "list_coupons"),
    (("推荐", "预算", "想买", "选购", "帮我挑"), "recommend_products"),
    (("商品", "找", "搜索", "耳机", "键盘", "风扇", "枕头", "详情", "介绍"), "search_products"),
]


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", ""))


def _find(names: list[str], hint: str) -> str | None:
    return next((n for n in names if hint in n), None)


def _text_of(content: Any) -> str:
    """兼容 core 1.8 标准内容块（list[dict]）与纯字符串两种 ToolMessage 形态。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def _parse(payload: str) -> Any:
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return None


def _summarize(messages: list[BaseMessage], question: str) -> str:
    """把真实工具返回的数据整理成面向用户的中文答复（不新增事实）。"""
    lines: list[str] = []
    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        data = _parse(_text_of(m.content))
        if not isinstance(data, dict):
            continue
        if not data.get("ok"):
            lines.append(f"- 查询未成功：{data.get('error', '未知原因')}")
            continue
        if "products" in data:
            for p in data["products"][:3]:
                stock = "有货" if p.get("in_stock") else "暂时缺货"
                lines.append(f"- {p['name']}（{p['sku']}）¥{p['price']:.2f}，{stock}，评分 {p['rating']}")
        if "order" in data:
            o = data["order"]
            node = o.get("logistics", {}).get("node", "")
            lines.append(f"- 订单 {o['order_id']}：{o['status']}，实付 ¥{o['total']:.2f}，物流 {node}")
        if "orders" in data:
            for o in data["orders"][:3]:
                lines.append(f"- {o['order_id']} {o['status']} ¥{o['total']:.2f}")
        if "payable" in data:
            c = data["coupons"][0]["title"] if data.get("coupons") else "未用券"
            lines.append(
                f"- {data['name']} × {data['quantity']}：原价 ¥{data['subtotal']:.2f}，"
                f"{c}，到手 ¥{data['payable']:.2f} CNY"
            )
        if "stock" in data and "products" not in data and "payable" not in data:
            lines.append(f"- {data.get('name', data['sku'])} 当前库存 {data['stock']} 件")
        if "coupons" in data and "payable" not in data:
            lines.extend(f"- 券 {c['code']}：{c['title']}" for c in data["coupons"])
        if "content" in data and data.get("content"):
            lines.append(f"- {data['topic']}政策：{data['content']}")
        if "eligible" in data:
            lines.append(f"- 退货资格：{'符合' if data['eligible'] else '不符合'}，{data['reason']}")
    if not lines:
        return "我已查询了相关工具，但没有拿到可用结果，请换个说法或补充订单号 / SKU。"
    prefix = "已为你核实到以下信息：\n" if "订单" in question or "查" in question else "为你整理如下：\n"
    return prefix + "\n".join(lines) + "\n\n以上均来自实时工具数据，如需下单请前往收银台。"


class ScriptedChatModel(BaseChatModel):
    """可离线运行的 BaseChatModel 实现，支持 tool_calls 与 token 级流式。"""

    model_name: str = "scripted-ecommerce"
    bound_tools: list[Any] = Field(default_factory=list)
    user_id: str = "u_1001"

    @property
    def _llm_type(self) -> str:
        return "scripted-ecommerce"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "backend": "offline-script"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self.model_copy(update={"bound_tools": list(tools or []), "user_id": self.user_id})

    def with_structured_output(self, schema: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _last_question(self, messages: list[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return _text_of(m.content)
        return ""

    def _plan(self, question: str, names: list[str]) -> list[dict[str, Any]]:
        q = question.strip()
        calls: list[dict[str, Any]] = []

        def add(hint: str, args: dict[str, Any]) -> None:
            name = _find(names, hint)
            if name and not any(c["name"] == name for c in calls):
                calls.append({"name": name, "args": args, "id": f"call_{len(calls) + 1}", "type": "tool_call"})

        # 多工具编排：预算推荐场景同时召回商品与优惠券
        if any(k in q for k in ("推荐", "预算", "帮我挑", "想买")):
            budget = 500.0 if any(k in q for k in ("500", "五百")) else 1000.0
            add("recommend_products", {"budget": budget, "preference": ""})
            add("list_coupons", {"user_id": self.user_id})
        elif any(k in q for k in ("退货", "能退", "退款", "售后资格")):
            add("check_after_sale_eligibility", {"order_id": "EC20261105002", "user_id": self.user_id})
            add("get_after_sale_policy", {"topic": "退货"})
        elif any(k in q for k in ("订单", "物流", "快递", "发货", "单号")):
            add("get_order", {"order_id": "EC20261118001", "user_id": self.user_id})
        elif any(k in q for k in ("多少钱", "到手", "用券", "券后", "算一下", "优惠")):
            add("calculate_price", {"sku": "SKU-1001", "quantity": 1, "coupon_code": "FULL100"})
        elif any(k in q for k in ("库存", "有货", "缺货", "剩几件")):
            add("check_inventory", {"sku": "SKU-1001"})
        elif any(k in q for k in ("政策", "保修", "发票", "价保", "换货规定")):
            add("get_after_sale_policy", {"topic": "退货"})
        elif any(k in q for k in ("券", "优惠券")):
            add("list_coupons", {"user_id": self.user_id})

        if not calls:
            add("search_products", {"keyword": _pick_keyword(q), "limit": 3})
        return calls

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        names = [_tool_name(t) for t in self.bound_tools]
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        question = self._last_question(messages)

        if tool_messages:
            answer = AIMessage(content=_summarize(tool_messages, question), id="ai_final")
        else:
            calls = self._plan(question, names)
            if not calls:
                answer = AIMessage(content="请告诉我你想查的商品、订单号或预算，我来帮你核实。", id="ai_ask")
            else:
                answer = AIMessage(content="", tool_calls=calls, id="ai_plan")

        return ChatResult(generations=[ChatGeneration(message=answer)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        msg = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs).generations[0].message
        if getattr(msg, "tool_calls", None):
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=msg.tool_calls, id=msg.id)
            )
            return
        text = msg.content or ""
        for i in range(0, len(text), 8):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text[i : i + 8], id=msg.id))


def _pick_keyword(question: str) -> str:
    for kw in ("耳机", "键盘", "风扇", "枕头", "乳胶", "降噪", "数码", "家居"):
        if kw in question:
            return kw
    return ""
