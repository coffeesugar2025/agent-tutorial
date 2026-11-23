"""LLM factory with a deterministic offline tool-calling model.

The offline model implements the same BaseChatModel contract as ChatOpenAI, so
switching to a real provider is a one-line config change (ECOM_LLM_PROVIDER=openai).
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field

from ..config import get_settings

_TOOL_CALL_ID = lambda: f"call_{uuid.uuid4().hex[:10]}"  # noqa: E731

_CANCEL_WORDS = ("请", "帮我", "我想", "一下", "请问", "给我", "我要")


class RuleBasedChatModel(BaseChatModel):
    """Offline model: rule-routed tool calling + deterministic answer rendering."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    bound_tools: list[Any] = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self) -> str:
        return "ecom-rule-based-offline"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "RuleBasedChatModel":
        return self.model_copy(update={"bound_tools": list(tools)})

    # ---------- helper logic (also directly unit-testable) ----------
    @staticmethod
    def pick_tool(text: str) -> str | None:
        text = (text or "").lower()
        has_order_id = bool(re.search(r"o\d{3,5}", text))
        if any(k in text for k in ("退款", "退货", "售后", "投诉", "换货")):
            return "initiate_refund" if has_order_id else "rag_search"
        if any(k in text for k in ("我的订单", "订单状态", "物流", "发货", "查订单", "订单")):
            if has_order_id:
                return "get_order"
            return "list_orders"
        if any(k in text for k in ("下单", "购买", "我要买", "来一", "来个")):
            return "create_order"
        if any(k in text for k in ("库存", "有货", "还有吗", "剩多少")):
            return "check_inventory"
        if any(k in text for k in ("商品", "推荐", "价格", "多少钱", "便宜", "搜索", "找", "耳机", "键盘", "椅子", "手表", "咖啡", "水杯", "充电")):
            return "search_products"
        if any(k in text for k in ("政策", "保修", "配送", "发票", "优惠券", "运费", "规则", "怎么", "如何")):
            return "rag_search"
        return None

    @staticmethod
    def _extract(text: str, pattern: str, default: str = "") -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        return match.group(0).upper() if match else default

    def _args_for(self, tool_name: str, text: str, user_id: str) -> dict[str, Any]:
        if tool_name == "search_products":
            query = text
            for word in _CANCEL_WORDS:
                query = query.replace(word, " ")
            return {"query": query.strip() or "商品"}
        if tool_name == "check_inventory":
            return {"product_id": self._extract(text, r"p\d{3,5}", "P001")}
        if tool_name == "create_order":
            pid = self._extract(text, r"p\d{3,5}", "P001")
            qty_match = re.search(r"(\d+)\s*(件|个|台|把)", text)
            qty = int(qty_match.group(1)) if qty_match else 1
            return {"customer_id": user_id or "U001",
                    "items_json": json.dumps([{"product_id": pid, "quantity": qty}], ensure_ascii=False)}
        if tool_name == "list_orders":
            return {"customer_id": user_id or "U001"}
        if tool_name == "get_order":
            return {"order_id": self._extract(text, r"o\d{3,5}", "O1001")}
        if tool_name == "initiate_refund":
            return {"order_id": self._extract(text, r"o\d{3,5}", "O1001"),
                    "reason": text.strip()[:80] or "用户申请"}
        if tool_name == "rag_search":
            return {"query": text.strip()[:120] or "售后政策"}
        return {}

    @staticmethod
    def _format_tool_result(name: str, content: str) -> str:
        try:
            data = json.loads(content)
        except Exception:
            return content
        if name == "search_products":
            if not isinstance(data, list) or not data:
                return "没有找到匹配的商品，试试其他关键词。"
            lines = [f"为你找到 {len(data)} 件相关商品："]
            for p in data:
                lines.append(f"- {p.get('id')} {p.get('name')} ¥{p.get('price')}，库存 {p.get('stock')}")
            return "\n".join(lines)
        if name == "check_inventory":
            if data.get("available"):
                return f"{data.get('name')}（{data.get('product_id')}）当前库存 {data.get('stock')} 件，可以下单。"
            return f"{data.get('name')} 暂时缺货，可以看看其他商品。"
        if name == "create_order":
            return (f"下单成功！订单号 {data.get('order_id')}，合计 ¥{data.get('total')}，"
                    f"当前状态 {data.get('status')}。")
        if name == "list_orders":
            if not data:
                return "你目前没有订单。"
            lines = [f"你共有 {len(data)} 笔订单："]
            for o in data:
                lines.append(f"- {o.get('id')} 金额 ¥{o.get('total')} 状态 {o.get('status')}")
            return "\n".join(lines)
        if name == "get_order":
            if data.get("error"):
                return f"查询失败：{data['error']}"
            lines = [f"订单 {data.get('id')}：状态 {data.get('status')}，金额 ¥{data.get('total')}。"]
            for i in data.get("items", []):
                lines.append(f"- {i.get('product_id')} × {i.get('quantity')}")
            return "\n".join(lines)
        if name == "initiate_refund":
            if data.get("error"):
                return f"退款申请未通过：{data['error']}"
            return f"退款申请已提交，单号 {data.get('order_id')}，状态 {data.get('status')}。"
        return content

    def _answer_from_tools(self, messages: list[BaseMessage]) -> str:
        tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
        ai_calls: list[str] = []
        for m in messages:
            if isinstance(m, AIMessage) and m.tool_calls:
                ai_calls.extend(str(c.get("name", "")) for c in m.tool_calls)
        answers = []
        for index, message in enumerate(tool_messages):
            name = message.name or (ai_calls[index] if index < len(ai_calls) else "")
            answers.append(self._format_tool_result(name, str(message.content)))
        return "\n\n".join(answers) or "已处理完成。"

    @staticmethod
    def _greeting() -> str:
        return ("你好，我是电商智能助手。我可以帮你：搜索与推荐商品、查询库存、下单、"
                "查询订单与物流、申请退款，以及解答售后/配送/发票等政策问题。请告诉我你需要什么？")

    # ---------- BaseChatModel contract ----------
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        user_text = ""
        system_text = ""
        for m in messages:
            if isinstance(m, SystemMessage):
                system_text += str(m.content or "") + "\n"
            elif isinstance(m, (HumanMessage,)) and not user_text:
                user_text = str(m.content or "")
        if not user_text:
            for m in reversed(messages):
                if not isinstance(m, (SystemMessage, ToolMessage)):
                    user_text = str(m.content or "")
                    break

        if any(isinstance(m, ToolMessage) for m in messages):
            message = AIMessage(content=self._answer_from_tools(messages))
            return ChatResult(generations=[ChatGeneration(message=message)])

        user_match = re.search(r"当前用户:\s*([A-Za-z0-9_\-]+)", system_text)
        user_id = user_match.group(1) if user_match else "U001"
        tool_name = self.pick_tool(user_text)
        available = {getattr(t, "name", "") for t in self.bound_tools}
        if tool_name and tool_name in available:
            call = {"name": tool_name, "args": self._args_for(tool_name, user_text, user_id),
                    "id": _TOOL_CALL_ID(), "type": "tool_call"}
            message = AIMessage(content="", tool_calls=[call])
        else:
            message = AIMessage(content=self._greeting() if not tool_name else
                                "当前角色没有可用工具来完成这个请求，我可以回答一般性问题。")
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_model() -> BaseChatModel:
    """按配置创建模型。

    优先级：
    1. 旧版 ``ECOM_LLM_PROVIDER=openai``（向后兼容）；
    2. 新版 ``ECOM_LLM_PROVIDERS`` 网关（deepseek / qwen / offline）；
    3. 离线规则模型兜底（零 Key 可运行）。

    网关使用惰性导入：``app.infra.llm_gateway`` 反向依赖本模块的 RuleBasedChatModel，
    直接在模块顶层导入会产生循环依赖。
    """
    settings = get_settings()
    if settings.llm_provider == "openai" and settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI  # type: ignore

            return ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key,
                              temperature=0, streaming=True)
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("ECOM_LLM_PROVIDER=openai 需要安装 langchain-openai") from exc

    from ..infra.settings import InfraSettings  # 惰性导入，避免循环依赖

    infra = InfraSettings.from_env()
    if any(name.strip().lower() != "offline"
           for name in infra.provider_names if isinstance(name, str)):
        from ..infra.llm_gateway import LLMGateway  # 惰性导入

        return LLMGateway(infra).create_chat_model()
    return RuleBasedChatModel()
