"""确定性 MockChatModel：无任何外部依赖即可跑通「提问 → 路由 → 工具 → 流式回答」。

行为约定（保证测试与 CI 可复现）：
1. 若本轮已执行过工具（最后一条消息是 ToolMessage）→ 基于工具结果生成最终答案；
2. 否则按关键词选择工具并发起 ``tool_calls``（含参数解析：预算/品牌/订单号）；
3. 无工具可调 → 直接给出兜底建议文案；
4. ``with_structured_output`` 走确定性填充：路由 → 关键词分类；重排 → 降序分数；
   裁判 → 基于关键词重叠判定通过。绝不发起网络请求。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from app.common.tokens import estimate_messages_tokens, estimate_tokens

BRANDS = ["Apple", "华为", "小米", "三星", "OPPO", "vivo", "荣耀", "联想", "戴尔", "索尼", "Bose", "索尼"]
ORDER_NO_RE = re.compile(r"(?<![A-Za-z0-9])(SO\d{10,16})(?![0-9])", re.IGNORECASE)
BUDGET_PATTERNS = [
    re.compile(r"(\d{3,6})\s*(?:元|块|rmb|RMB)?\s*(?:以内|以下|之内|封顶|左右)"),
    re.compile(r"预算\s*(\d{3,6})"),
    re.compile(r"不(?:超过|高于|多于)\s*(\d{3,6})"),
    re.compile(r"低于\s*(\d{3,6})"),
]
SKU_RE = re.compile(r"(?:SKU[-_ ]?)?([A-Z]{2}-?\d{3,4})")

PRODUCT_KEYWORDS = ("推荐", "买", "选购", "找", "哪个好", "手机", "耳机", "笔记本", "平板", "相机", "手表", "电视", "音箱")
KNOWLEDGE_KEYWORDS = ("政策", "规则", "运费", "保修", "发票", "怎么退", "如何退", "多久发货", "售后流程", "条款", "说明")
ANALYTICS_KEYWORDS = ("销售", "营收", "gmv", "GMV", "订单量", "统计", "报表", "分析", "排名", "趋势", "多少单", "客单价")
HUMAN_KEYWORDS = ("人工", "投诉", "客服电话", "转接")


class MockChatModel(BaseChatModel):
    """确定性聊天模型（离线可用）。"""

    model_name: str = "mock-chat"
    temperature: float = 0.0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: int = 0

    @property
    def _llm_type(self) -> str:
        return "mock-chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "tool_count": len(self.tools)}

    # ------------------------------------------------------------------
    # 工具绑定
    # ------------------------------------------------------------------
    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Any:
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.model_copy(update={"tools": converted})

    @property
    def tool_names(self) -> list[str]:
        return [str(t.get("function", {}).get("name", "")) for t in self.tools if t.get("function")]

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._decide(messages)
        text = message.content if isinstance(message.content, str) else ""
        for index in range(0, len(text), 6):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text[index : index + 6]))
        chunk_message = AIMessageChunk(
            content="",
            tool_calls=message.tool_calls,
            usage_metadata=message.usage_metadata,
            response_metadata=message.response_metadata,
        )
        yield ChatGenerationChunk(message=chunk_message)

    # ------------------------------------------------------------------
    # 决策
    # ------------------------------------------------------------------
    def _decide(self, messages: list[BaseMessage]) -> AIMessage:
        human = self._last_human(messages)
        system = self._system_text(messages)
        tool_results = self._tool_results_after_last_human(messages)
        prompt_tokens = estimate_messages_tokens(messages)

        if tool_results:
            text = self._answer_from_tools(human, tool_results)
            return self._finish(text, prompt_tokens, finish_reason="stop")

        if self._looks_like_summary(system):
            text = self._summarize(human)
            return self._finish(text, prompt_tokens)

        decision = self._pick_tool(human)
        if decision and decision[0] in self.tool_names:
            name, args = decision
            call_id = f"call_{abs(hash((name, json.dumps(args, sort_keys=True, ensure_ascii=False)))) % 10_000_000}"
            return AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
                usage_metadata={
                    "input_tokens": prompt_tokens,
                    "output_tokens": 16,
                    "total_tokens": prompt_tokens + 16,
                },
                response_metadata={"model_name": self.model_name, "finish_reason": "tool_calls"},
            )

        text = self._fallback_answer(human)
        return self._finish(text, prompt_tokens)

    def _finish(self, text: str, prompt_tokens: int, finish_reason: str = "stop") -> AIMessage:
        return AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": prompt_tokens,
                "output_tokens": estimate_tokens(text),
                "total_tokens": prompt_tokens + estimate_tokens(text),
            },
            response_metadata={"model_name": self.model_name, "finish_reason": finish_reason},
        )

    # ------------------------------------------------------------------
    # 消息辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _last_human(messages: list[BaseMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return message.content if isinstance(message.content, str) else str(message.content)
        return ""

    @staticmethod
    def _system_text(messages: list[BaseMessage]) -> str:
        parts = [
            str(m.content)
            for m in messages
            if isinstance(m, SystemMessage)
            and isinstance(m.content, str)
        ]
        return "\n".join(parts)

    @staticmethod
    def _tool_results_after_last_human(messages: list[BaseMessage]) -> list[ToolMessage]:
        results: list[ToolMessage] = []
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                break
            if isinstance(message, ToolMessage):
                results.append(message)
        return list(reversed(results))

    @staticmethod
    def _looks_like_summary(system: str) -> bool:
        return ("摘要" in system or "总结" in system) and "电商" not in system

    # ------------------------------------------------------------------
    # 工具选择
    # ------------------------------------------------------------------
    def _pick_tool(self, human: str) -> tuple[str, dict[str, Any]] | None:
        text = human or ""
        order_no = self._extract_order_no(text)
        lower = text.lower()

        if ("退款" in text or "退钱" in text) and any(w in text for w in ("申请", "办理", "发起", "帮我退", "退掉")):
            return "create_refund_request", {
                "orderNo": order_no or "SO202611230001",
                "reason": text[:120] or "用户申请退款",
            }
        if ("退款" in text or "退货" in text) and any(
            w in text for w in ("资格", "能不能", "可以吗", "条件", "支持", "可以退")
        ):
            return "check_refund_eligibility", {"orderNo": order_no or "SO202611230001"}
        if any(w in text for w in ("物流", "快递", "到哪", "发货", "签收", "运单")):
            return "get_logistics", {"orderNo": order_no or "SO202611230001"}
        if order_no or "我的订单" in text or "订单" in text:
            if order_no:
                return "get_order", {"orderNo": order_no}
            return "list_orders", {"status": None, "limit": 5}
        if any(w in text for w in HUMAN_KEYWORDS):
            return "escalate_to_human", {"reason": text[:80], "summary": text[:200]}
        if any(w in text for w in KNOWLEDGE_KEYWORDS):
            return "search_knowledge", {"query": text[:80], "topK": 3}
        if any(w in text for w in ANALYTICS_KEYWORDS) or "gmv" in lower:
            return "text2sql", {"question": text[:120]}
        if any(w in text for w in ("对比", "比较")):
            skus = SKU_RE.findall(text.upper())
            if len(skus) >= 2:
                return "compare_products", {"skus": [s.upper() for s in skus[:3]]}
            return "search_products", {"query": text[:80], "topK": 3}
        if any(w in text for w in PRODUCT_KEYWORDS):
            args: dict[str, Any] = {"query": text[:80], "topK": 5}
            budget = self._extract_budget(text)
            if budget:
                args["maxPrice"] = budget
            brand = next((b for b in BRANDS if b.lower() in lower or b in text), None)
            if brand:
                args["brands"] = [brand]
            return "search_products", args
        return None

    @staticmethod
    def _extract_order_no(text: str) -> str | None:
        match = ORDER_NO_RE.search(text)
        return match.group(1).upper() if match else None

    @staticmethod
    def _extract_budget(text: str) -> float | None:
        for pattern in BUDGET_PATTERNS:
            match = pattern.search(text or "")
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------------
    # 答案生成
    # ------------------------------------------------------------------
    def _answer_from_tools(self, human: str, results: list[ToolMessage]) -> str:
        blocks: list[str] = []
        for message in results:
            name = message.name or "tool"
            payload = self._parse_payload(message.content)
            blocks.append(self._render_tool_result(name, payload))
        head = self._lead_in(human)
        return f"{head}\n\n" + "\n\n".join(b for b in blocks if b)

    @staticmethod
    def _lead_in(human: str) -> str:
        if any(w in human for w in ("物流", "快递")):
            return "已为你查到物流信息："
        if "订单" in human:
            return "已为你查询订单："
        if any(w in human for w in ("退款", "退货")):
            return "已核实该订单的售后情况："
        if any(w in human for w in ANALYTICS_KEYWORDS):
            return "经营数据查询结果如下："
        if any(w in human for w in KNOWLEDGE_KEYWORDS):
            return "根据知识库检索到以下依据："
        return "已为你整理结果："

    @staticmethod
    def _parse_payload(content: Any) -> Any:
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        if not isinstance(content, str):
            return content
        stripped = content.strip()
        # 兼容被 <untrusted_data> 包裹的工具输出（安全层会把工具返回标记为"数据非指令"），
        # 取出标签内的内容再尝试 JSON 解析。
        wrapped = re.search(r"<untrusted_data[^>]*>\s*(.*?)\s*</untrusted_data>", stripped, re.S)
        if wrapped:
            stripped = wrapped.group(1).strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
        return stripped

    def _render_tool_result(self, name: str, payload: Any) -> str:
        if not isinstance(payload, dict):
            # 兜底：工具返回非结构化内容时不要炸，截断展示即可
            return f"- {name} 返回：{str(payload)[:300]}"
        if payload.get("error"):
            return f"- {name} 执行失败：{payload['error']}"
        if name == "search_products":
            items = (payload or {}).get("items") or []
            if not items:
                return "- 没有找到符合条件的商品，可以放宽预算或换个关键词试试。"
            lines = []
            for index, item in enumerate(items[:3], start=1):
                price = item.get("price")
                lines.append(
                    f"{index}. {item.get('title', '')}（SKU {item.get('sku', '')}）"
                    f"{'¥' + str(price) if price is not None else ''}"
                    f"{'，评分 ' + str(item.get('rating')) if item.get('rating') is not None else ''}"
                )
            return "为你筛选出以下几款：\n" + "\n".join(lines)
        if name == "compare_products":
            items = (payload or {}).get("items") or []
            if not items:
                return "- 没有可对比的商品。"
            return "对比结论：\n" + "\n".join(
                f"- {i.get('sku')}：¥{i.get('price')}，{i.get('highlight', '')}" for i in items
            )
        if name in ("get_order", "list_orders"):
            orders = payload.get("items") if isinstance(payload, dict) else None
            if orders:
                return "最近订单：\n" + "\n".join(
                    f"- {o.get('orderNo')}｜{o.get('status')}｜¥{o.get('payAmount')}" for o in orders
                )
            order = (payload or {}).get("order") or payload
            return (
                f"- 订单号 {order.get('orderNo')}\n"
                f"- 状态 {order.get('status')}\n"
                f"- 实付 ¥{order.get('payAmount')}\n"
                f"- 下单时间 {order.get('createdAt')}"
            )
        if name == "get_logistics":
            data = payload or {}
            events = data.get("events") or []
            tail = "\n".join(f"  · {e.get('time')} {e.get('desc')}" for e in events[-2:])
            return (
                f"- 承运商：{data.get('company')}（{data.get('trackingNo')}）\n"
                f"- 当前状态：{data.get('status')}｜最新动态：{data.get('latestEvent')}"
                + (f"\n{tail}" if tail else "")
            )
        if name == "check_refund_eligibility":
            data = payload or {}
            state = "符合" if data.get("eligible") else "暂不符合"
            return f"- 退款资格：{state}\n- 说明：{data.get('reason', '')}"
        if name == "search_knowledge":
            items = (payload or {}).get("items") or []
            if not items:
                return "- 知识库没有检索到相关规定，建议转人工确认。"
            return "\n".join(
                f"- 《{item.get('title')}》：{(item.get('snippet') or '')[:120]}" for item in items[:3]
            )
        if name == "text2sql":
            data = payload or {}
            rows = data.get("rows") or []
            return f"- 执行的查询：{data.get('sql')}\n- 结果：{json.dumps(rows, ensure_ascii=False)}"
        if name == "escalate_to_human":
            data = payload or {}
            return f"- 已创建人工工单 #{data.get('ticketId')}，客服会尽快联系你。"
        if isinstance(payload, dict):
            return "- " + json.dumps(payload, ensure_ascii=False)[:400]
        return f"- {str(payload)[:400]}"

    @staticmethod
    def _summarize(human: str) -> str:
        snippet = (human or "").strip().replace("\n", " ")[:120]
        return f"摘要：用户关注「{snippet}」，诉求为商品咨询与售后处理。"

    @staticmethod
    def _fallback_answer(human: str) -> str:
        if any(w in human for w in ("你好", "hi", "hello", "在吗")):
            return (
                "你好，我是星图商城智能助手 👋\n"
                "我可以帮你：\n"
                "1. 挑选商品、比价、对比推荐；\n"
                "2. 查询订单、物流与退款资格；\n"
                "3. 解答退换货、保修等政策问题。\n"
                "直接说需求即可，例如「帮我找 5000 以内的拍照手机」。"
            )
        return (
            "我可以帮你选购商品、查询订单物流、核查退款资格或解答售后政策。\n"
            "请补充更具体的信息（例如预算、品牌、订单号），我马上为你处理。"
        )

    # ------------------------------------------------------------------
    # 结构化输出（确定性）
    # ------------------------------------------------------------------
    def with_structured_output(
        self,
        schema: dict[str, Any] | type,
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Any:
        def _run(messages: Any) -> Any:
            human = self._last_human(messages if isinstance(messages, list) else [])
            parsed = self._structured_payload(schema, human)
            if not include_raw:
                return parsed
            raw = AIMessage(content=json.dumps(_dump(parsed), ensure_ascii=False, default=str))
            return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return RunnableLambda(_run)

    def _structured_payload(self, schema: Any, human: str) -> Any:
        fields = _schema_fields(schema)
        if not fields:
            return {}
        values: dict[str, Any] = {}
        if "agent_type" in fields:
            agent = self._classify_agent(human)
            values["agent_type"] = agent
            values["reason"] = {
                "SHOPPING": "商品导购意图（选购/比价/推荐）",
                "SERVICE": "售后服务意图（订单/物流/退款）",
                "OPS": "经营分析意图（报表/统计/趋势）",
            }[agent]
            if "confidence" in fields:
                values["confidence"] = 0.92
        if "scores" in fields:
            count = _count_from_prompt(human)
            values["scores"] = [round(0.95 - 0.1 * i, 3) for i in range(count)]
        if "ranking" in fields:
            count = _count_from_prompt(human)
            values["ranking"] = list(range(count))
        if "passed" in fields:
            values["passed"] = True
            values["score"] = 0.88
            if "reason" in fields:
                values["reason"] = "回答覆盖了参考要点，且未出现越权承诺。"
        for name, annotation in fields.items():
            if name in values:
                continue
            values[name] = _default_for(annotation, human)
        values = {k: v for k, v in values.items() if k in fields}
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema(**values)
        return values

    @staticmethod
    def _classify_agent(human: str) -> str:
        text = human or ""
        if any(w in text for w in ("订单", "物流", "退款", "退货", "快递", "售后", "发票", "签收")):
            return "SERVICE"
        if any(w in text for w in ANALYTICS_KEYWORDS) or "gmv" in text.lower():
            return "OPS"
        return "SHOPPING"


# ---------------------------------------------------------------------------
# 结构化辅助
# ---------------------------------------------------------------------------
def _schema_fields(schema: Any) -> dict[str, Any]:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return {name: field.annotation for name, field in schema.model_fields.items()}
    if isinstance(schema, dict):
        properties = schema.get("properties") or {}
        return {str(name): (prop or {}).get("type") for name, prop in properties.items()}
    return {}


def _count_from_prompt(human: str) -> int:
    match = re.search(r"共\s*(\d{1,2})\s*(?:条|个|段)", human or "")
    if match:
        return max(int(match.group(1)), 1)
    return 3


def _default_for(annotation: Any, human: str) -> Any:
    origin = getattr(annotation, "__origin__", None)
    if annotation in (str,):
        return (human or "")[:200]
    if annotation in (int,):
        return 1
    if annotation in (float,):
        return 0.8
    if annotation in (bool,):
        return True
    if origin in (list, list) or annotation in (list,):
        return []
    if origin in (dict, dict) or annotation in (dict,):
        return {}
    return None


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


def build_mock_model(temperature: float = 0.0, latency_ms: int = 0) -> MockChatModel:
    """工厂：返回可复用的 Mock 模型实例。"""
    return MockChatModel(temperature=temperature, latency_ms=latency_ms)


__all__ = ["MockChatModel", "build_mock_model"]
